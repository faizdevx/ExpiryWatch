from typing import Annotated

from fastapi import APIRouter, Path, status

from app.auth import WriteAccess
from app.database import DbSession
from app.models import Product
from app.schemas.common import Limit, Offset, Page
from app.schemas.product import (
    BARCODE_PATTERN,
    BarcodeLookup,
    ProductCreate,
    ProductRead,
    ProductUpdate,
)
from app.services import barcode_service, product_service
from app.services.barcode_service import BarcodeClient

router = APIRouter(prefix="/products", tags=["products"])


@router.post(
    "", response_model=ProductRead, status_code=status.HTTP_201_CREATED, dependencies=[WriteAccess]
)
def create_product(data: ProductCreate, db: DbSession) -> Product:
    return product_service.create_product(db, data)


@router.get("", response_model=Page[ProductRead])
def list_products(
    db: DbSession,
    q: str | None = None,
    category: str | None = None,
    brand: str | None = None,
    barcode: str | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> dict:
    items, total = product_service.list_products(
        db, q=q, category=category, brand=brand, barcode=barcode, limit=limit, offset=offset
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


# Requires the key though it is a read: anyone could otherwise burn the 15 req/min provider quota.
@router.get("/lookup/{barcode}", dependencies=[WriteAccess])
async def lookup_barcode(
    barcode: Annotated[str, Path(pattern=BARCODE_PATTERN)], client: BarcodeClient
) -> BarcodeLookup:
    return await barcode_service.lookup_barcode(client, barcode)


@router.get("/{product_id}", response_model=ProductRead)
def get_product(product_id: int, db: DbSession) -> Product:
    return product_service.get_product(db, product_id)


@router.patch("/{product_id}", response_model=ProductRead, dependencies=[WriteAccess])
def update_product(product_id: int, data: ProductUpdate, db: DbSession) -> Product:
    return product_service.update_product(db, product_id, data)


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[WriteAccess])
def delete_product(product_id: int, db: DbSession) -> None:
    product_service.delete_product(db, product_id)
