import pytest
from pydantic import ValidationError

from app.config import Settings

URL = "postgresql+psycopg://user:pass@localhost/db"


def make_settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **{"database_url": URL, "app_env": "development", **overrides})


@pytest.mark.parametrize(
    "given", ["postgres://u:p@h/db", "postgresql://u:p@h/db", "postgresql+psycopg://u:p@h/db"]
)
def test_database_url_always_uses_psycopg(given: str) -> None:
    assert make_settings(database_url=given).database_url == "postgresql+psycopg://u:p@h/db"


@pytest.mark.parametrize("key", [None, "", "   "])
def test_production_refuses_to_start_without_api_key(key: str | None) -> None:
    with pytest.raises(ValidationError, match="APP_API_KEY"):
        make_settings(app_env="production", app_api_key=key)


def test_production_starts_with_api_key() -> None:
    assert make_settings(app_env="production", app_api_key="secret").app_api_key is not None


def test_development_allows_missing_api_key() -> None:
    assert make_settings(app_api_key="").app_api_key is None


def test_api_key_is_hidden_from_repr() -> None:
    assert "secret-value" not in repr(make_settings(app_api_key="secret-value"))


def test_unknown_timezone_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Unknown timezone"):
        make_settings(app_timezone="Mars/Olympus")


def test_warning_window_cannot_be_negative() -> None:
    with pytest.raises(ValidationError):
        make_settings(expiry_warning_days=-1)
