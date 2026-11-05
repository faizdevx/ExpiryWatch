from functools import lru_cache
from typing import Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    app_env: Literal["development", "test", "production"] = "development"
    app_api_key: SecretStr | None = None  # SecretStr keeps the key out of logs and reprs.
    external_api_base_url: str = "https://world.openfoodfacts.org"
    expiry_warning_days: int = Field(default=30, ge=0, le=3650)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    app_timezone: str = "UTC"

    @field_validator("database_url")
    @classmethod
    def use_psycopg_driver(cls, url: str) -> str:
        # Hosts such as Render hand out postgres:// URLs, which SQLAlchemy rejects.
        scheme, separator, rest = url.partition("://")
        if separator and scheme in {"postgres", "postgresql"}:
            return f"postgresql+psycopg://{rest}"
        return url

    @field_validator("app_api_key", mode="before")
    @classmethod
    def blank_key_means_unset(cls, key: object) -> object:
        return None if isinstance(key, str) and not key.strip() else key

    @field_validator("app_timezone")
    @classmethod
    def timezone_must_exist(cls, name: str) -> str:
        try:
            ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError(f"Unknown timezone: {name}") from error
        return name

    @model_validator(mode="after")
    def production_requires_api_key(self) -> Self:
        if self.app_env == "production" and self.app_api_key is None:
            raise ValueError("APP_API_KEY must be set when APP_ENV=production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
