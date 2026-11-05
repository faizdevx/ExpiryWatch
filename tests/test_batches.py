from datetime import date

import pytest

from app.main import app
from app.services.expiry_service import get_today
from tests.test_products import assert_error

BATCHES = "/api/v1/batches"


def test_create_batch(client, make_product):
    product = make_product()
    response = client.post(
        BATCHES,
        json={
            "product_id": product["id"],
            "batch_number": "B001",
            "quantity": 10,
            "expiry_date": "2026-11-08",
            "received_at": "2026-11-01",
            "location": "Shelf A",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["product_id"] == product["id"]
    assert (body["batch_number"], body["quantity"]) == ("B001", 10)
    assert (body["expiry_date"], body["received_at"]) == ("2026-11-08", "2026-11-01")
    assert body["location"] == "Shelf A"


def test_received_at_defaults_to_today(client, make_product):
    app.dependency_overrides[get_today] = lambda: date(2026, 3, 15)
    payload = {"product_id": make_product()["id"], "quantity": 1, "expiry_date": "2026-12-01"}
    assert client.post(BATCHES, json=payload).json()["received_at"] == "2026-03-15"


def test_multiple_batches_keep_their_own_expiry_dates(client, make_product, make_batch):
    # The ExpiryWatch example: 50 packets of milk across three batches.
    product_id = make_product()["id"]
    expected = {
        "B001": (10, "2026-11-08"),
        "B002": (20, "2026-11-15"),
        "B003": (20, "2026-11-25"),
    }
    for number, (quantity, expiry) in expected.items():
        make_batch(
            product_id=product_id, batch_number=number, quantity=quantity, expiry_date=expiry
        )

    items = client.get(BATCHES, params={"product_id": product_id}).json()["items"]
    actual = {item["batch_number"]: (item["quantity"], item["expiry_date"]) for item in items}
    assert actual == expected


def test_past_expiry_date_is_accepted(make_batch):
    assert make_batch(expiry_date="2020-01-01")["expiry_date"] == "2020-01-01"


@pytest.mark.parametrize(
    "change",
    [
        {"quantity": -1},
        {"quantity": 2_147_483_648},
        {"quantity": 1.5},
        {"expiry_date": "soon"},
        {"expiry_date": "2026-02-30"},
        {"expiry_date": None},
    ],
)
def test_create_rejects_invalid_values(client, make_product, change):
    payload = {
        "product_id": make_product()["id"],
        "quantity": 1,
        "expiry_date": "2026-11-08",
        **change,
    }
    assert_error(client.post(BATCHES, json=payload), 422, "validation_error")


def test_create_rejects_unknown_product(client):
    payload = {"product_id": 999999, "quantity": 1, "expiry_date": "2026-11-08"}
    assert_error(client.post(BATCHES, json=payload), 404, "product_not_found")


def test_create_rejects_out_of_range_product_id(client):
    payload = {"product_id": 2**70, "quantity": 1, "expiry_date": "2026-11-08"}
    assert_error(client.post(BATCHES, json=payload), 422, "invalid_data")


def test_retrieve_batch(client, make_batch):
    batch = make_batch()
    assert client.get(f"{BATCHES}/{batch['id']}").json() == batch


@pytest.mark.parametrize(
    ("method", "kwargs"),
    [("get", {}), ("patch", {"json": {"quantity": 1}}), ("delete", {})],
)
def test_batch_not_found(client, method, kwargs):
    response = getattr(client, method)(f"{BATCHES}/999999", **kwargs)
    assert_error(response, 404, "batch_not_found")


def test_update_batch_leaves_other_batches_alone(client, make_product, make_batch):
    product_id = make_product()["id"]
    target = make_batch(product_id=product_id, quantity=10, expiry_date="2026-11-08")
    other = make_batch(product_id=product_id, quantity=20, expiry_date="2026-11-15")

    response = client.patch(
        f"{BATCHES}/{target['id']}", json={"quantity": 3, "expiry_date": "2026-12-01"}
    )

    assert response.status_code == 200
    assert (response.json()["quantity"], response.json()["expiry_date"]) == (3, "2026-12-01")
    assert client.get(f"{BATCHES}/{other['id']}").json() == other


@pytest.mark.parametrize(
    "change",
    [
        {"quantity": None},
        {"expiry_date": None},
        {"received_at": None},
        {"quantity": -5},
        {"product_id": 1},
    ],
)
def test_update_rejects_invalid_changes(client, make_batch, change):
    batch = make_batch()
    response = client.patch(f"{BATCHES}/{batch['id']}", json=change)
    assert_error(response, 422, "validation_error")
    assert client.get(f"{BATCHES}/{batch['id']}").json() == batch


def test_update_can_clear_location(client, make_batch):
    batch = make_batch(location="Shelf A")
    response = client.patch(f"{BATCHES}/{batch['id']}", json={"location": None})
    assert response.json()["location"] is None


def test_delete_batch(client, make_batch):
    batch = make_batch()
    assert client.delete(f"{BATCHES}/{batch['id']}").status_code == 204
    assert client.get(f"{BATCHES}/{batch['id']}").status_code == 404


def test_zero_quantity_hidden_from_list_but_retrievable(client, make_batch):
    batch = make_batch(quantity=0)
    assert client.get(BATCHES).json()["total"] == 0
    assert client.get(BATCHES, params={"include_depleted": True}).json()["total"] == 1
    assert client.get(f"{BATCHES}/{batch['id']}").status_code == 200


def test_filter_by_location_and_expiry_range(client, make_product, make_batch):
    product_id = make_product()["id"]
    for number, expiry, location in [
        ("A", "2026-01-01", "Shelf"),
        ("B", "2026-06-01", "Shelf"),
        ("C", "2026-12-31", "Fridge"),
    ]:
        make_batch(
            product_id=product_id, batch_number=number, expiry_date=expiry, location=location
        )

    def numbers(**params) -> list[str]:
        return [item["batch_number"] for item in client.get(BATCHES, params=params).json()["items"]]

    assert numbers(location="fridge") == ["C"]
    assert numbers(expiry_from="2026-06-01") == ["B", "C"]
    assert numbers(expiry_to="2026-06-01") == ["A", "B"]
    assert numbers(expiry_from="2026-02-01", expiry_to="2026-07-01") == ["B"]


def test_sort_by_expiry_with_stable_ties(client, make_product, make_batch):
    product_id = make_product()["id"]
    late = make_batch(product_id=product_id, expiry_date="2026-12-01")
    tie_one = make_batch(product_id=product_id, expiry_date="2026-01-01")
    tie_two = make_batch(product_id=product_id, expiry_date="2026-01-01")

    def ids(**params) -> list[int]:
        return [item["id"] for item in client.get(BATCHES, params=params).json()["items"]]

    assert ids() == [tie_one["id"], tie_two["id"], late["id"]]
    assert ids(sort="expiry_desc") == [late["id"], tie_one["id"], tie_two["id"]]


def test_invalid_sort_is_rejected(client):
    assert_error(client.get(BATCHES, params={"sort": "name"}), 422, "validation_error")
