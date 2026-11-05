import pytest

from app.config import Settings, get_settings
from app.main import app
from tests.conftest import TEST_API_KEY
from tests.test_products import assert_error

PRODUCTS = "/api/v1/products"
WRITES = [
    ("post", "/api/v1/products"),
    ("patch", "/api/v1/products/1"),
    ("delete", "/api/v1/products/1"),
    ("post", "/api/v1/batches"),
    ("patch", "/api/v1/batches/1"),
    ("delete", "/api/v1/batches/1"),
]


@pytest.mark.parametrize(("method", "path"), WRITES)
def test_writes_require_a_key(client, method, path):
    del client.headers["X-API-Key"]
    assert_error(client.request(method, path), 401, "invalid_api_key")


@pytest.mark.parametrize("key", ["wrong", TEST_API_KEY + "x", "", "clé".encode("latin-1")])
def test_wrong_key_is_rejected(client, key):
    response = client.post(PRODUCTS, json={"name": "Milk"}, headers={"X-API-Key": key})
    assert_error(response, 401, "invalid_api_key")


def test_correct_key_is_accepted(client):
    assert client.post(PRODUCTS, json={"name": "Milk"}).status_code == 201


def test_reads_are_public(client):
    del client.headers["X-API-Key"]
    assert client.get(PRODUCTS).status_code == 200
    assert client.get("/api/v1/batches").status_code == 200


def test_no_configured_key_leaves_writes_open(client):
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, database_url="postgresql://u:p@h/d", app_env="development", app_api_key=None
    )
    del client.headers["X-API-Key"]
    assert client.post(PRODUCTS, json={"name": "Milk"}).status_code == 201
