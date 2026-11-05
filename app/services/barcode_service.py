"""Open Food Facts barcode lookup. Only this module knows the provider's response format."""

import logging
import re
from typing import Annotated

import httpx
from fastapi import Depends, Request, status

from app.exceptions.handlers import AppError
from app.schemas.product import BARCODE_PATTERN, BarcodeLookup

logger = logging.getLogger(__name__)

# Docs mark v2 deprecated. v3.6 omits "categories", so categories_tags_en is requested instead.
LOOKUP_PATH = "/api/v3.6/product/{barcode}.json"
LOOKUP_FIELDS = "code,product_name,brands,categories_tags_en"
USER_AGENT = "ExpiryWatch/0.1.0 (https://github.com/faizdevx/ExpiryWatch)"
TIMEOUT = httpx.Timeout(5.0, connect=3.0)
MAX_LABEL_LENGTH = 255  # Matches the products columns, so a lookup result can always be saved.
LANGUAGE_PREFIX = re.compile(r"^[a-z]{2,3}:")


def create_client(base_url: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=base_url, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT})


def get_barcode_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.barcode_client


BarcodeClient = Annotated[httpx.AsyncClient, Depends(get_barcode_client)]


def _provider_failure(reason: str, barcode: str) -> AppError:
    logger.warning("Barcode provider failure for %s: %s", barcode, reason)
    return AppError(
        status.HTTP_502_BAD_GATEWAY, "provider_error", "The barcode provider is unavailable"
    )


def _clean_text(value: object) -> str | None:
    """Every provider field is optional and untrusted: anything but real text becomes None."""
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()[:MAX_LABEL_LENGTH]


def _pick_category(tags: object) -> str | None:
    """Tags run general to specific, so the last one is best. "pt:..." tags are untranslated."""
    if not isinstance(tags, list):
        return None
    translated = [tag for tag in tags if isinstance(tag, str) and not LANGUAGE_PREFIX.match(tag)]
    return _clean_text(translated[-1]) if translated else None


def _error_ids(body: dict) -> set[str]:
    errors = body.get("errors")
    if not isinstance(errors, list):
        return set()
    ids = set()
    for error in errors:
        message = error.get("message") if isinstance(error, dict) else None
        if isinstance(message, dict) and isinstance(message.get("id"), str):
            ids.add(message["id"])
    return ids


def _parse_product(body: dict, barcode: str) -> BarcodeLookup:
    product = body["product"]
    code = body.get("code")
    # The provider pads codes (11 digits becomes 13). Its form is canonical when it is usable.
    usable_code = isinstance(code, str) and re.fullmatch(BARCODE_PATTERN, code)
    return BarcodeLookup(
        barcode=code if usable_code else barcode,
        name=_clean_text(product.get("product_name")),
        brand=_clean_text(product.get("brands")),
        category=_pick_category(product.get("categories_tags_en")),
    )


async def lookup_barcode(client: httpx.AsyncClient, barcode: str) -> BarcodeLookup:
    # barcode is digits only (route validation), so it is safe to place in the path.
    try:
        response = await client.get(
            LOOKUP_PATH.format(barcode=barcode), params={"fields": LOOKUP_FIELDS}
        )
    except httpx.TimeoutException as error:
        logger.warning("Barcode provider timed out for %s: %r", barcode, error)
        raise AppError(
            status.HTTP_504_GATEWAY_TIMEOUT,
            "provider_timeout",
            "The barcode provider did not respond in time",
        ) from error
    except httpx.HTTPError as error:
        raise _provider_failure(repr(error), barcode) from error

    if response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
        logger.warning("Barcode provider rate limited the lookup for %s", barcode)
        raise AppError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "provider_rate_limited",
            "The barcode provider is rate limiting requests. Try again in a minute",
        )
    if response.status_code not in (status.HTTP_200_OK, status.HTTP_404_NOT_FOUND):
        raise _provider_failure(f"HTTP {response.status_code}", barcode)

    try:
        body = response.json()
    except ValueError as error:
        raise _provider_failure("response is not JSON", barcode) from error
    if not isinstance(body, dict):
        raise _provider_failure("response is not a JSON object", barcode)

    # Read the body before trusting a 404: a proxy's HTML 404 is an outage, not a missing product.
    error_ids = _error_ids(body)
    if "invalid_code" in error_ids:
        raise AppError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "invalid_barcode",
            f"{barcode} is not a valid barcode",
        )
    if "product_not_found" in error_ids:
        raise AppError(
            status.HTTP_404_NOT_FOUND,
            "barcode_not_found",
            f"No product found for barcode {barcode}. It can still be registered manually",
        )
    if response.status_code != status.HTTP_200_OK or not isinstance(body.get("product"), dict):
        raise _provider_failure("unexpected response shape", barcode)
    return _parse_product(body, barcode)
