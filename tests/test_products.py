import pytest

PRODUCTS = "/api/v1/products"


def assert_error(response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "details"}
    assert body["error"]["code"] == code


def test_create_product(client):
    response = client.post(
        PRODUCTS,
        json={
            "name": "  Milk  ",
            "barcode": "3017624010701",
            "brand": "Amul",
            "category": "Dairy",
            "description": "1L packet",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["id"] > 0
    assert body["name"] == "Milk"
    assert body["barcode"] == "3017624010701"
    assert body["created_at"] and body["updated_at"]


def test_create_requires_name(client):
    assert_error(client.post(PRODUCTS, json={"brand": "Amul"}), 422, "validation_error")


def test_create_rejects_unknown_field(client):
    response = client.post(PRODUCTS, json={"name": "Milk", "price": 5})
    assert_error(response, 422, "validation_error")


@pytest.mark.parametrize("barcode", ["1234567", "123456789012345", "12345abc", "١٢٣٤٥٦٧٨"])
def test_create_rejects_malformed_barcode(client, barcode):
    response = client.post(PRODUCTS, json={"name": "Milk", "barcode": barcode})
    assert_error(response, 422, "validation_error")


def test_blank_barcodes_become_null_and_never_conflict(client):
    for _ in range(2):
        response = client.post(PRODUCTS, json={"name": "Loose rice", "barcode": "  "})
        assert response.status_code == 201
        assert response.json()["barcode"] is None


def test_duplicate_barcode_on_create(client, make_product):
    make_product(barcode="12345678")
    response = client.post(PRODUCTS, json={"name": "Other", "barcode": "12345678"})
    assert_error(response, 409, "duplicate_barcode")


def test_duplicate_barcode_on_update(client, make_product):
    make_product(barcode="12345678")
    other = make_product(barcode="87654321")
    response = client.patch(f"{PRODUCTS}/{other['id']}", json={"barcode": "12345678"})
    assert_error(response, 409, "duplicate_barcode")


def test_retrieve_product(client, make_product):
    product = make_product(name="Bread")
    response = client.get(f"{PRODUCTS}/{product['id']}")
    assert response.status_code == 200
    assert response.json() == product


@pytest.mark.parametrize(
    ("method", "kwargs"),
    [("get", {}), ("patch", {"json": {"name": "x"}}), ("delete", {})],
)
def test_product_not_found(client, method, kwargs):
    response = getattr(client, method)(f"{PRODUCTS}/999999", **kwargs)
    assert_error(response, 404, "product_not_found")


def test_list_paginates_and_reports_total(client, make_product):
    for name in ("A", "B", "C"):
        make_product(name=name)
    body = client.get(PRODUCTS, params={"limit": 2, "offset": 1}).json()
    assert [item["name"] for item in body["items"]] == ["B", "C"]
    assert (body["total"], body["limit"], body["offset"]) == (3, 2, 1)


def test_list_rejects_oversized_limit(client):
    assert_error(client.get(PRODUCTS, params={"limit": 201}), 422, "validation_error")


def test_search_matches_name_or_brand(client, make_product):
    make_product(name="Whole Milk", brand="Amul")
    make_product(name="Butter", brand="Milky Way")
    make_product(name="Bread", brand="Harvest")
    body = client.get(PRODUCTS, params={"q": "milk"}).json()
    assert {item["name"] for item in body["items"]} == {"Whole Milk", "Butter"}


def test_search_treats_wildcards_literally(client, make_product):
    make_product(name="Milk")
    make_product(name="Cocoa 50% dark")
    body = client.get(PRODUCTS, params={"q": "%"}).json()
    assert [item["name"] for item in body["items"]] == ["Cocoa 50% dark"]


def test_filter_by_category_brand_barcode(client, make_product):
    make_product(name="A", category="Dairy", brand="Amul", barcode="11111111")
    make_product(name="B", category="Bakery", brand="Amul")
    for params, expected in [
        ({"category": "dairy"}, {"A"}),
        ({"brand": "AMUL"}, {"A", "B"}),
        ({"barcode": "11111111"}, {"A"}),
    ]:
        body = client.get(PRODUCTS, params=params).json()
        assert {item["name"] for item in body["items"]} == expected


def test_update_changes_only_sent_fields(client, make_product):
    product = make_product(name="Milk", brand="Amul", category="Dairy")
    response = client.patch(f"{PRODUCTS}/{product['id']}", json={"brand": "Mother Dairy"})
    assert response.status_code == 200
    body = response.json()
    assert (body["name"], body["brand"], body["category"]) == ("Milk", "Mother Dairy", "Dairy")


def test_update_can_clear_nullable_field(client, make_product):
    product = make_product(barcode="12345678")
    response = client.patch(f"{PRODUCTS}/{product['id']}", json={"barcode": None})
    assert response.status_code == 200
    assert response.json()["barcode"] is None


def test_update_rejects_null_name(client, make_product):
    product = make_product()
    response = client.patch(f"{PRODUCTS}/{product['id']}", json={"name": None})
    assert_error(response, 422, "validation_error")


def test_keeping_own_barcode_is_not_a_conflict(client, make_product):
    product = make_product(barcode="12345678")
    response = client.patch(f"{PRODUCTS}/{product['id']}", json={"barcode": "12345678"})
    assert response.status_code == 200


def test_delete_product_without_batches(client, make_product):
    product = make_product()
    assert client.delete(f"{PRODUCTS}/{product['id']}").status_code == 204
    assert client.get(f"{PRODUCTS}/{product['id']}").status_code == 404


def test_delete_blocked_while_stock_exists(client, make_product, make_batch):
    product = make_product()
    depleted = make_batch(product_id=product["id"], quantity=0)
    make_batch(product_id=product["id"], quantity=5)
    response = client.delete(f"{PRODUCTS}/{product['id']}")
    assert_error(response, 409, "product_has_stock")
    # The rollback must also restore the zero-quantity batch removed earlier in that transaction.
    assert client.get(f"/api/v1/batches/{depleted['id']}").status_code == 200
    assert client.get(f"{PRODUCTS}/{product['id']}").status_code == 200


def test_delete_blocked_by_expired_stock(client, make_product, make_batch):
    product = make_product()
    make_batch(product_id=product["id"], quantity=1, expiry_date="2020-01-01")
    assert_error(client.delete(f"{PRODUCTS}/{product['id']}"), 409, "product_has_stock")


def test_delete_removes_zero_quantity_batches(client, make_product, make_batch):
    product = make_product()
    batch = make_batch(product_id=product["id"], quantity=0)
    assert client.delete(f"{PRODUCTS}/{product['id']}").status_code == 204
    assert client.get(f"/api/v1/batches/{batch['id']}").status_code == 404


def test_postgres_rejections_become_client_errors(client):
    # NUL bytes pass Pydantic but Postgres refuses them. Must be a 422, never a 500.
    response = client.post(PRODUCTS, json={"name": "Mi\x00lk"})
    assert_error(response, 422, "invalid_data")
    assert_error(client.get(PRODUCTS, params={"q": "a\x00b"}), 422, "invalid_data")


def test_huge_id_is_not_a_server_error(client):
    assert_error(client.get(f"{PRODUCTS}/{2**70}"), 422, "invalid_data")


def test_explicit_null_barcode_is_accepted(client):
    response = client.post(PRODUCTS, json={"name": "Loose rice", "barcode": None})
    assert response.status_code == 201
    assert response.json()["barcode"] is None


def test_unknown_route_uses_error_format(client):
    assert_error(client.get("/api/v1/nope"), 404, "not_found")
