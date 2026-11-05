from datetime import date, timedelta

import pytest
from sqlalchemy import event

from app.config import Settings, get_settings
from app.database import engine
from app.main import app
from app.models import InventoryBatch
from app.services.expiry_service import ExpiryClock, ExpiryStatus, get_today
from tests.test_products import assert_error

TODAY = date(2026, 11, 5)
BATCHES = "/api/v1/batches"
ALERTS = "/api/v1/alerts"
SUMMARY = "/api/v1/dashboard/summary"


def day(offset: int) -> str:
    return (TODAY + timedelta(days=offset)).isoformat()


@pytest.fixture
def fixed_today(client):
    app.dependency_overrides[get_today] = lambda: TODAY


def use_warning_window(days: int) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        database_url="postgresql://u:p@h/d",
        app_env="test",
        expiry_warning_days=days,
    )


def expiries(response) -> list[str]:
    assert response.status_code == 200, response.text
    return [item["expiry_date"] for item in response.json()["items"]]


@pytest.mark.parametrize(
    ("offset", "expected"),
    [
        (-365, ExpiryStatus.EXPIRED),
        (-1, ExpiryStatus.EXPIRED),
        (0, ExpiryStatus.EXPIRING_SOON),
        (1, ExpiryStatus.EXPIRING_SOON),
        (30, ExpiryStatus.EXPIRING_SOON),
        (31, ExpiryStatus.SAFE),
        (365, ExpiryStatus.SAFE),
    ],
)
def test_classification_boundaries(offset, expected):
    clock = ExpiryClock(today=TODAY, warning_days=30)
    assert clock.classify(TODAY + timedelta(days=offset)) == expected


def test_zero_day_window_covers_only_today():
    clock = ExpiryClock(today=TODAY, warning_days=0)
    assert clock.classify(TODAY) == ExpiryStatus.EXPIRING_SOON
    assert clock.classify(TODAY + timedelta(days=1)) == ExpiryStatus.SAFE


def test_classification_handles_month_and_leap_year_edges():
    clock = ExpiryClock(today=date(2028, 2, 28), warning_days=1)
    assert clock.classify(date(2028, 2, 29)) == ExpiryStatus.EXPIRING_SOON
    assert clock.classify(date(2028, 3, 1)) == ExpiryStatus.SAFE


@pytest.mark.parametrize("offset", [-2, -1, 0, 1, 29, 30, 31, 32])
def test_python_rule_and_sql_filter_agree(client, fixed_today, make_batch, offset):
    make_batch(expiry_date=day(offset))
    clock = ExpiryClock(today=TODAY, warning_days=30)
    expected = clock.classify(TODAY + timedelta(days=offset))

    for status in ExpiryStatus:
        found = client.get(BATCHES, params={"expiry_status": status.value}).json()["total"]
        assert found == (1 if status == expected else 0), status


def test_batch_response_has_derived_status(client, fixed_today, make_product, make_batch):
    product = make_product(name="Bread")
    batch = make_batch(product_id=product["id"], expiry_date=day(-3))
    assert batch["status"] == "EXPIRED"
    assert batch["days_until_expiry"] == -3
    assert batch["product_name"] == "Bread"


def test_status_changes_with_the_date_and_no_write(client, fixed_today, make_batch):
    batch = make_batch(expiry_date=day(1))
    url = f"{BATCHES}/{batch['id']}"
    assert client.get(url).json()["status"] == "EXPIRING_SOON"
    app.dependency_overrides[get_today] = lambda: TODAY + timedelta(days=2)
    assert client.get(url).json()["status"] == "EXPIRED"


def test_status_is_not_stored():
    assert "status" not in InventoryBatch.__table__.columns


def test_warning_window_is_configurable(client, fixed_today, make_batch):
    batch = make_batch(expiry_date=day(8))
    url = f"{BATCHES}/{batch['id']}"
    assert client.get(url).json()["status"] == "EXPIRING_SOON"
    use_warning_window(7)
    assert client.get(url).json()["status"] == "SAFE"
    assert client.get(ALERTS).json()["total"] == 0


def test_today_follows_configured_timezone():
    def today_in(zone: str) -> date:
        return get_today(
            Settings(_env_file=None, database_url="postgresql://u:p@h/d", app_timezone=zone)
        )

    # UTC+14 and UTC-11 are 25 hours apart, so these are on different dates at any moment.
    assert today_in("Pacific/Kiritimati") > today_in("Pacific/Pago_Pago")


def test_all_alerts_are_expired_and_expiring_in_fefo_order(client, fixed_today, make_batch):
    for offset in (31, 30, 0, -1):
        make_batch(expiry_date=day(offset))
    assert expiries(client.get(ALERTS)) == [day(-1), day(0), day(30)]


def test_expired_alerts_stop_before_today(client, fixed_today, make_batch):
    for offset in (0, -1, -30):
        make_batch(expiry_date=day(offset))
    assert expiries(client.get(f"{ALERTS}/expired")) == [day(-30), day(-1)]


def test_expiring_uses_within_days_and_excludes_expired(client, fixed_today, make_batch):
    for offset in (-1, 0, 7, 8):
        make_batch(expiry_date=day(offset))
    response = client.get(f"{ALERTS}/expiring", params={"within_days": 7})
    assert expiries(response) == [day(0), day(7)]


def test_expiring_with_zero_days_means_today_only(client, fixed_today, make_batch):
    for offset in (0, 1):
        make_batch(expiry_date=day(offset))
    response = client.get(f"{ALERTS}/expiring", params={"within_days": 0})
    assert expiries(response) == [day(0)]


def test_expiring_defaults_to_configured_window(client, fixed_today, make_batch):
    for offset in (30, 31):
        make_batch(expiry_date=day(offset))
    assert expiries(client.get(f"{ALERTS}/expiring")) == [day(30)]


def test_within_days_wider_than_window_keeps_true_status(client, fixed_today, make_batch):
    make_batch(expiry_date=day(60))
    item = client.get(f"{ALERTS}/expiring", params={"within_days": 90}).json()["items"][0]
    assert item["status"] == "SAFE"


@pytest.mark.parametrize("within_days", [-1, 3651, "soon"])
def test_within_days_is_validated(client, within_days):
    response = client.get(f"{ALERTS}/expiring", params={"within_days": within_days})
    assert_error(response, 422, "validation_error")


@pytest.mark.parametrize("path", ["", "/expired", "/expiring"])
def test_zero_quantity_never_alerts(client, fixed_today, make_batch, path):
    make_batch(quantity=0, expiry_date=day(-1))
    make_batch(quantity=0, expiry_date=day(0))
    assert client.get(f"{ALERTS}{path}").json()["total"] == 0


def test_batch_that_reaches_zero_stops_alerting(client, fixed_today, make_batch):
    batch = make_batch(quantity=5, expiry_date=day(-1))
    assert client.get(ALERTS).json()["total"] == 1
    client.patch(f"{BATCHES}/{batch['id']}", json={"quantity": 0})
    assert client.get(ALERTS).json()["total"] == 0


def test_alerts_paginate(client, fixed_today, make_batch):
    for offset in (-3, -2, -1):
        make_batch(expiry_date=day(offset))
    response = client.get(f"{ALERTS}/expired", params={"limit": 1, "offset": 1})
    assert expiries(response) == [day(-2)]
    assert response.json()["total"] == 3


def test_status_filter_combines_with_other_filters(client, fixed_today, make_batch):
    make_batch(expiry_date=day(-1), location="Fridge")
    make_batch(expiry_date=day(-2), location="Shelf")
    make_batch(expiry_date=day(5), location="Fridge")
    response = client.get(BATCHES, params={"expiry_status": "EXPIRED", "location": "fridge"})
    assert expiries(response) == [day(-1)]
    response = client.get(BATCHES, params={"expiry_status": "EXPIRED", "expiry_from": day(-1)})
    assert expiries(response) == [day(-1)]


def test_invalid_status_filter_is_rejected(client):
    response = client.get(BATCHES, params={"expiry_status": "ROTTEN"})
    assert_error(response, 422, "validation_error")


def test_summary_of_empty_database_is_all_zeros(client, fixed_today):
    response = client.get(SUMMARY)
    assert response.status_code == 200
    assert set(response.json().values()) == {0}


def test_summary_counts(client, fixed_today, make_product, make_batch):
    product_id = make_product()["id"]
    make_product(name="No stock")
    make_batch(product_id=product_id, quantity=10, expiry_date=day(-1))
    make_batch(product_id=product_id, quantity=20, expiry_date=day(0))
    make_batch(product_id=product_id, quantity=30, expiry_date=day(30))
    make_batch(product_id=product_id, quantity=40, expiry_date=day(31))
    make_batch(product_id=product_id, quantity=0, expiry_date=day(-5))
    make_batch(product_id=product_id, quantity=0, expiry_date=day(5))

    assert client.get(SUMMARY).json() == {
        "total_products": 2,
        "total_active_batches": 4,
        "total_units": 100,
        "expired_batches": 1,
        "expiring_soon_batches": 2,
        "expired_units": 10,
        "expiring_soon_units": 50,
    }


def test_summary_units_can_exceed_a_postgres_integer(client, fixed_today, make_product, make_batch):
    product_id = make_product()["id"]
    make_batch(product_id=product_id, quantity=2_147_483_647)
    make_batch(product_id=product_id, quantity=2_147_483_647)
    assert client.get(SUMMARY).json()["total_units"] == 4_294_967_294


def test_list_does_not_run_one_query_per_batch(client, db, make_batch):
    for _ in range(3):
        make_batch()  # Each gets its own product, so a lazy load would need 3 extra queries.
    db.expunge_all()  # Otherwise the products are cached and no lazy load could ever show up.

    statements = []

    def record(_conn, _cursor, statement, *_rest):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        assert client.get(BATCHES).json()["total"] == 3
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert len(statements) == 2, statements  # One COUNT, one SELECT with the join.
