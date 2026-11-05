import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.barcode_service import USER_AGENT, create_client, get_barcode_client
from tests.test_products import assert_error

BARCODE = "3017624010701"
LOOKUP = f"/api/v1/products/lookup/{BARCODE}"
SECRET_DETAIL = "internal-provider-detail"

NOT_FOUND_BODY = {
    "code": BARCODE,
    "errors": [{"message": {"id": "product_not_found"}}],
    "result": {"id": "product_not_found"},
    "status": "failure",
}
INVALID_BODY = {
    "code": "00000000",
    "errors": [{"message": {"id": "invalid_code"}}, {"message": {"id": "product_not_found"}}],
    "result": {"id": "product_not_found"},
    "status": "failure",
}


def found_body(**product) -> dict:
    return {
        "code": BARCODE,
        "errors": [],
        "product": product,
        "result": {"id": "product_found"},
        "status": "success",
    }


@pytest.fixture
def provider(client):
    """Replace the network: each test decides what the provider does. Records every request."""
    requests: list[httpx.Request] = []

    def respond_with(result) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if isinstance(result, Exception):
                raise result
            return result

        mock = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="http://provider.test",
            headers={"User-Agent": USER_AGENT},
        )
        app.dependency_overrides[get_barcode_client] = lambda: mock

    respond_with.requests = requests
    return respond_with


def test_successful_lookup(client, provider):
    provider(
        httpx.Response(
            200,
            json=found_body(
                product_name="Nutella",
                brands="Ferrero",
                categories_tags_en=["Breakfasts", "Spreads", "Cocoa spreads", "de:Other"],
            ),
        )
    )
    response = client.get(LOOKUP)
    assert response.status_code == 200
    assert response.json() == {
        "barcode": BARCODE,
        "name": "Nutella",
        "brand": "Ferrero",
        "category": "Cocoa spreads",
    }


def test_request_sent_to_provider(client, provider):
    provider(httpx.Response(200, json=found_body(product_name="Nutella")))
    client.get(LOOKUP)
    request = provider.requests[0]
    assert request.url.path == f"/api/v3.6/product/{BARCODE}.json"
    assert request.url.params["fields"] == "code,product_name,brands,categories_tags_en"
    assert request.headers["User-Agent"] == USER_AGENT
    assert "x-api-key" not in request.headers  # Our secret must never reach a third party.


def test_success_with_warnings_counts_as_found(client, provider):
    body = found_body(product_name="Sugo") | {"status": "success_with_warnings"}
    provider(httpx.Response(200, json=body))
    assert client.get(LOOKUP).json()["name"] == "Sugo"


def test_provider_normalized_code_is_returned(client, provider):
    provider(httpx.Response(200, json=found_body(product_name="Sugo") | {"code": "0099999999999"}))
    response = client.get("/api/v1/products/lookup/99999999999")
    assert response.json()["barcode"] == "0099999999999"


def test_unusable_provider_code_falls_back_to_request(client, provider):
    provider(httpx.Response(200, json=found_body(product_name="Sugo") | {"code": "not-digits"}))
    assert client.get(LOOKUP).json()["barcode"] == BARCODE


def test_product_with_no_details_returns_nulls(client, provider):
    provider(httpx.Response(200, json=found_body()))
    assert client.get(LOOKUP).json() == {
        "barcode": BARCODE,
        "name": None,
        "brand": None,
        "category": None,
    }


@pytest.mark.parametrize(
    "product",
    [
        {"product_name": 123, "brands": ["x"], "categories_tags_en": "Spreads"},
        {"product_name": "   ", "brands": "", "categories_tags_en": []},
        {"product_name": None, "brands": None, "categories_tags_en": [None, 5, "fr:Pates"]},
    ],
)
def test_wrong_typed_fields_become_null(client, provider, product):
    provider(httpx.Response(200, json=found_body(**product)))
    body = client.get(LOOKUP).json()
    assert (body["name"], body["brand"], body["category"]) == (None, None, None)


def test_lookup_result_can_always_be_registered(client, provider):
    provider(
        httpx.Response(
            200,
            json=found_body(
                product_name="N" * 400, brands="B" * 400, categories_tags_en=["C" * 400]
            ),
        )
    )
    found = client.get(LOOKUP).json()
    response = client.post("/api/v1/products", json=found)
    assert response.status_code == 201, response.text
    assert response.json()["barcode"] == BARCODE


def test_product_not_found(client, provider):
    provider(httpx.Response(404, json=NOT_FOUND_BODY))
    assert_error(client.get(LOOKUP), 404, "barcode_not_found")


def test_invalid_barcode_reported_by_provider(client, provider):
    provider(httpx.Response(404, json=INVALID_BODY))
    assert_error(client.get(LOOKUP), 422, "invalid_barcode")


@pytest.mark.parametrize("barcode", ["abc", "1234567", "123456789012345", "12345678x", "١٢٣٤٥٦٧٨"])
def test_malformed_barcode_never_reaches_provider(client, provider, barcode):
    provider(httpx.Response(200, json=found_body()))
    assert_error(client.get(f"/api/v1/products/lookup/{barcode}"), 422, "validation_error")
    assert provider.requests == []


@pytest.mark.parametrize(
    "error",
    [httpx.ConnectTimeout("slow"), httpx.ReadTimeout("slow"), httpx.PoolTimeout("slow")],
)
def test_timeout(client, provider, error):
    provider(error)
    assert_error(client.get(LOOKUP), 504, "provider_timeout")


@pytest.mark.parametrize(
    "error",
    [httpx.ConnectError(SECRET_DETAIL), httpx.RemoteProtocolError(SECRET_DETAIL)],
)
def test_connection_failure(client, provider, error):
    provider(error)
    response = client.get(LOOKUP)
    assert_error(response, 502, "provider_error")
    assert SECRET_DETAIL not in response.text


@pytest.mark.parametrize("status", [500, 502, 503, 400, 403, 301])
def test_unexpected_status(client, provider, status):
    provider(httpx.Response(status, text=SECRET_DETAIL))
    response = client.get(LOOKUP)
    assert_error(response, 502, "provider_error")
    assert SECRET_DETAIL not in response.text


def test_rate_limited(client, provider):
    provider(httpx.Response(429, text=SECRET_DETAIL))
    response = client.get(LOOKUP)
    assert_error(response, 503, "provider_rate_limited")
    assert SECRET_DETAIL not in response.text


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>not json</html>"),
        httpx.Response(200, json=["not", "an", "object"]),
        httpx.Response(200, json={"status": "success"}),
        httpx.Response(200, json={"status": "success", "product": "Nutella"}),
        httpx.Response(200, json={"errors": "nonsense", "product": None}),
        httpx.Response(200, json={"errors": ["nonsense", {"message": 5}]}),
        httpx.Response(404, text="<html>proxy 404</html>"),
        httpx.Response(404, json={"unexpected": True}),
    ],
)
def test_malformed_response(client, provider, response):
    provider(response)
    assert_error(client.get(LOOKUP), 502, "provider_error")


def test_lookup_requires_api_key(client, provider):
    provider(httpx.Response(200, json=found_body()))
    del client.headers["X-API-Key"]
    assert_error(client.get(LOOKUP), 401, "invalid_api_key")
    assert provider.requests == []


def test_manual_registration_works_while_provider_is_down(client, provider):
    provider(httpx.ConnectError("down"))
    assert client.get(LOOKUP).status_code == 502
    response = client.post("/api/v1/products", json={"name": "Milk", "barcode": BARCODE})
    assert response.status_code == 201
    assert provider.requests[1:] == []


def test_lookup_saves_nothing(client, provider):
    provider(httpx.Response(200, json=found_body(product_name="Nutella")))
    client.get(LOOKUP)
    assert client.get("/api/v1/products").json()["total"] == 0


def test_real_client_is_configured_with_timeout_and_identity():
    real = create_client("http://provider.test")
    assert real.timeout.connect == 3.0
    assert real.timeout.read == 5.0
    assert real.headers["User-Agent"] == USER_AGENT
    assert str(real.base_url).startswith("http://provider.test")


def test_lifespan_opens_and_closes_the_shared_client():
    with TestClient(app):
        shared = app.state.barcode_client
        assert isinstance(shared, httpx.AsyncClient)
        assert not shared.is_closed
    assert shared.is_closed
