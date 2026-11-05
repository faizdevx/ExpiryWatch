import os

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.config import Settings

TEST_API_KEY = "test-api-key"

# Must run before anything imports app.database, which builds its engine from DATABASE_URL.
_base_url = make_url(os.environ.get("TEST_DATABASE_URL") or Settings().database_url)
if "TEST_DATABASE_URL" not in os.environ:
    _base_url = _base_url.set(database=f"{_base_url.database}_test")
if not _base_url.database.endswith("_test"):
    raise RuntimeError(f"Refusing to run tests on {_base_url.database!r}: name must end in _test")

os.environ.update(
    DATABASE_URL=_base_url.render_as_string(hide_password=False),
    APP_ENV="test",
    APP_API_KEY=TEST_API_KEY,
    APP_TIMEZONE="UTC",
    EXPIRY_WARNING_DAYS="30",
)

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.database import engine, get_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def test_database():
    """Rebuild the test database through Alembic, so the migrations are tested too."""
    admin = create_engine(_base_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    name = _base_url.database
    with admin.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    admin.dispose()
    command.upgrade(Config("alembic.ini"), "head")
    yield
    engine.dispose()


@pytest.fixture
def db():
    """One outer transaction per test, rolled back at the end. Service commits hit a savepoint."""
    with engine.connect() as connection:
        transaction = connection.begin()
        session = Session(
            bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        yield session
        session.close()
        transaction.rollback()


@pytest.fixture
def client(db):
    def override_get_db():
        # Like production, where closing the session discards whatever a failed request left.
        try:
            yield db
        finally:
            db.rollback()

    app.dependency_overrides[get_db] = override_get_db
    # No "with": skipping lifespan avoids building a real HTTP client (and SSL context) per test,
    # and means a test that forgets to mock the provider fails instead of using the network.
    yield TestClient(app, headers={"X-API-Key": TEST_API_KEY})
    app.dependency_overrides.clear()


@pytest.fixture
def make_product(client):
    def create(**fields) -> dict:
        response = client.post("/api/v1/products", json={"name": "Milk", **fields})
        assert response.status_code == 201, response.text
        return response.json()

    return create


@pytest.fixture
def make_batch(client, make_product):
    def create(**fields) -> dict:
        if "product_id" not in fields:
            fields["product_id"] = make_product()["id"]
        payload = {"quantity": 10, "expiry_date": "2026-11-08", **fields}
        response = client.post("/api/v1/batches", json=payload)
        assert response.status_code == 201, response.text
        return response.json()

    return create
