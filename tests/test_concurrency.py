"""Races between real requests. These commit for real, so they use their own cleanup."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.database import SessionLocal
from app.main import app
from app.models import InventoryBatch, Product
from tests.conftest import TEST_API_KEY

PRODUCTS = "/api/v1/products"
BATCHES = "/api/v1/batches"
ROUNDS = 15


def wipe() -> None:
    with SessionLocal() as session:
        session.execute(delete(InventoryBatch))
        session.execute(delete(Product))
        session.commit()


@pytest.fixture
def api():
    wipe()
    yield TestClient(app, headers={"X-API-Key": TEST_API_KEY})
    wipe()


def simultaneously(*actions):
    """Run each action in its own thread, released together to maximize overlap."""
    barrier = Barrier(len(actions))

    def run(action):
        barrier.wait()
        return action()

    with ThreadPoolExecutor(max_workers=len(actions)) as pool:
        return list(pool.map(run, actions))


def create_product(api, **fields) -> int:
    return api.post(PRODUCTS, json={"name": "Milk", **fields}).json()["id"]


def create_batch(api, product_id: int, quantity: int) -> int:
    payload = {"product_id": product_id, "quantity": quantity, "expiry_date": "2026-11-08"}
    return api.post(BATCHES, json=payload).json()["id"]


def test_same_barcode_created_at_once_succeeds_exactly_once(api):
    def post():
        return api.post(PRODUCTS, json={"name": "Milk", "barcode": "12345678"}).status_code

    assert sorted(simultaneously(*[post] * 8)) == [201] + [409] * 7


def test_delete_product_racing_new_batch_never_orphans_stock(api):
    outcomes = set()
    for _ in range(ROUNDS):
        product_id = create_product(api)
        payload = {"product_id": product_id, "quantity": 5, "expiry_date": "2026-11-08"}
        deleted, created = simultaneously(
            lambda product=product_id: api.delete(f"{PRODUCTS}/{product}").status_code,
            lambda body=payload: api.post(BATCHES, json=body).status_code,
        )
        outcomes.add((deleted, created))
    # Either the delete won and the batch was refused, or the batch won and the delete was refused.
    assert outcomes <= {(204, 404), (409, 201)}


def test_delete_product_racing_restock_never_loses_stock(api):
    outcomes = set()
    for _ in range(ROUNDS):
        product_id = create_product(api)
        batch_id = create_batch(api, product_id, 0)
        deleted, restocked = simultaneously(
            lambda product=product_id: api.delete(f"{PRODUCTS}/{product}").status_code,
            lambda batch=batch_id: (
                api.patch(f"{BATCHES}/{batch}", json={"quantity": 5}).status_code
            ),
        )
        outcomes.add((deleted, restocked))
        if restocked == 200:
            # A restock that reported success must still exist, along with its product.
            assert api.get(f"{BATCHES}/{batch_id}").json()["quantity"] == 5
            assert deleted == 409
    assert outcomes <= {(409, 200), (204, 404), (204, 409)}


def test_patch_racing_delete_of_the_same_batch(api):
    product_id = create_product(api)
    outcomes = set()
    for _ in range(ROUNDS):
        batch_id = create_batch(api, product_id, 5)
        deleted, patched = simultaneously(
            lambda batch=batch_id: api.delete(f"{BATCHES}/{batch}").status_code,
            lambda batch=batch_id: (
                api.patch(f"{BATCHES}/{batch}", json={"quantity": 1}).status_code
            ),
        )
        outcomes.add((deleted, patched))
    assert outcomes <= {(204, 200), (204, 404), (204, 409)}


def test_two_deletes_of_the_same_batch(api):
    product_id = create_product(api)
    for _ in range(ROUNDS):
        batch_id = create_batch(api, product_id, 5)

        def remove(batch=batch_id):
            return api.delete(f"{BATCHES}/{batch}").status_code

        statuses = simultaneously(remove, remove)
        assert all(status in (204, 404) for status in statuses), statuses
        assert 204 in statuses


def test_no_batch_is_left_without_a_product(api):
    product_id = create_product(api)
    create_batch(api, product_id, 5)
    with SessionLocal() as session:
        orphans = session.scalars(
            select(InventoryBatch.id).where(InventoryBatch.product_id.not_in(select(Product.id)))
        ).all()
    assert orphans == []
