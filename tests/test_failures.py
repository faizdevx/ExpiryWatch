"""What clients see, and what the log records, when something goes wrong."""

import logging

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.orm.exc import StaleDataError

from app.database import engine, get_db
from app.main import app
from app.services import product_service
from tests.test_products import assert_error

PRODUCTS = "/api/v1/products"
INTERNAL_DETAIL = "postgresql://user:hunter2@internal-host/db"


class BrokenSession:
    """Stands in for a session when the database cannot be reached."""

    def __init__(self, error: Exception) -> None:
        self.error = error

    def __getattr__(self, _name: str):
        def fail(*_args, **_kwargs):
            raise self.error

        return fail


def database_down() -> OperationalError:
    return OperationalError("SELECT 1", {}, Exception(INTERNAL_DETAIL))


@pytest.fixture
def broken_db(client):
    def use(error: Exception) -> None:
        app.dependency_overrides[get_db] = lambda: BrokenSession(error)

    return use


def test_health_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_health_reports_database_outage(client, broken_db, caplog):
    broken_db(database_down())
    response = client.get("/health")
    assert response.status_code == 503
    assert response.json() == {"status": "unhealthy", "database": "unavailable"}
    assert INTERNAL_DETAIL not in response.text
    assert "could not reach the database" in caplog.text


@pytest.mark.parametrize(
    "error", [database_down(), PoolTimeoutError("QueuePool limit reached")], ids=["down", "pool"]
)
def test_crud_during_database_outage(client, broken_db, caplog, error):
    broken_db(error)
    response = client.get(f"{PRODUCTS}/1")
    assert_error(response, 503, "database_unavailable")
    assert INTERNAL_DETAIL not in response.text
    assert "Database unavailable on GET" in caplog.text


def test_row_deleted_during_a_write_is_a_conflict(client, broken_db):
    broken_db(StaleDataError("UPDATE expected 1 row, matched 0"))
    response = client.patch(f"{PRODUCTS}/1", json={"name": "New"})
    assert_error(response, 409, "concurrent_modification")
    assert "UPDATE" not in response.text


def test_unexpected_error_is_generic_for_client_and_detailed_in_log(monkeypatch, caplog):
    def explode(*_args, **_kwargs):
        raise RuntimeError(INTERNAL_DETAIL)

    monkeypatch.setattr(product_service, "list_products", explode)
    # raise_server_exceptions=False: see the response a real client would get.
    response = TestClient(app, raise_server_exceptions=False).get(PRODUCTS)

    assert_error(response, 500, "internal_error")
    assert INTERNAL_DETAIL not in response.text
    assert "Traceback" not in response.text
    assert "Unexpected error on GET /api/v1/products" in caplog.text
    assert INTERNAL_DETAIL in caplog.text


def test_sql_parameters_are_not_in_exception_text():
    assert engine.hide_parameters is True


def test_malformed_json_body(client):
    response = client.post(
        PRODUCTS, content="{not json", headers={"Content-Type": "application/json"}
    )
    assert_error(response, 422, "validation_error")


def test_missing_body(client):
    assert_error(client.post(PRODUCTS), 422, "validation_error")


def test_validation_error_does_not_echo_input(client):
    response = client.post(PRODUCTS, json={"name": "x", "barcode": "my-private-value"})
    assert_error(response, 422, "validation_error")
    assert "my-private-value" not in response.text
    assert response.json()["error"]["details"][0]["field"] == "body.barcode"


def test_blank_name_is_rejected(client):
    assert_error(client.post(PRODUCTS, json={"name": "   "}), 422, "validation_error")


def test_empty_patch_changes_nothing(client, make_product):
    product = make_product(brand="Amul")
    response = client.patch(f"{PRODUCTS}/{product['id']}", json={})
    assert response.status_code == 200
    assert response.json() == product


def test_wrong_method_uses_error_format(client):
    assert_error(client.put(PRODUCTS), 405, "method_not_allowed")


def test_api_key_never_appears_in_logs(client, caplog):
    caplog.set_level(logging.DEBUG)
    client.post(PRODUCTS, json={"name": "Milk"}, headers={"X-API-Key": "a-wrong-secret-key"})
    client.post(PRODUCTS, json={"name": "Milk"})
    assert "a-wrong-secret-key" not in caplog.text
    assert client.headers["X-API-Key"] not in caplog.text


def test_startup_and_shutdown_are_logged(caplog):
    caplog.set_level(logging.INFO, logger="app.main")
    with TestClient(app):
        assert "ExpiryWatch starting" in caplog.text
        assert "shutting down" not in caplog.text
    assert "ExpiryWatch shutting down" in caplog.text


def test_lookup_route_uses_the_client_from_lifespan(caplog):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "12345678", "product": {"product_name": "Tea"}})

    mock = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://p.test")
    with TestClient(app, headers={"X-API-Key": "test-api-key"}) as client:
        app.state.barcode_client = mock
        response = client.get(f"{PRODUCTS}/lookup/12345678")
    assert response.json()["name"] == "Tea"
