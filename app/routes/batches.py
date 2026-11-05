from datetime import date

from fastapi import APIRouter, status

from app.auth import WriteAccess
from app.database import DbSession
from app.models import InventoryBatch
from app.schemas.batch import BatchCreate, BatchRead, BatchUpdate
from app.schemas.common import Limit, Offset, Page
from app.services import batch_service
from app.services.batch_service import BatchSort
from app.services.expiry_service import Today

router = APIRouter(prefix="/batches", tags=["batches"])


@router.post(
    "", response_model=BatchRead, status_code=status.HTTP_201_CREATED, dependencies=[WriteAccess]
)
def create_batch(data: BatchCreate, db: DbSession, today: Today) -> InventoryBatch:
    return batch_service.create_batch(db, data, today)


@router.get("", response_model=Page[BatchRead])
def list_batches(
    db: DbSession,
    product_id: int | None = None,
    location: str | None = None,
    expiry_from: date | None = None,
    expiry_to: date | None = None,
    include_depleted: bool = False,
    sort: BatchSort = "expiry_asc",
    limit: Limit = 50,
    offset: Offset = 0,
) -> dict:
    items, total = batch_service.list_batches(
        db,
        product_id=product_id,
        location=location,
        expiry_from=expiry_from,
        expiry_to=expiry_to,
        include_depleted=include_depleted,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/{batch_id}", response_model=BatchRead)
def get_batch(batch_id: int, db: DbSession) -> InventoryBatch:
    return batch_service.get_batch(db, batch_id)


@router.patch("/{batch_id}", response_model=BatchRead, dependencies=[WriteAccess])
def update_batch(batch_id: int, data: BatchUpdate, db: DbSession) -> InventoryBatch:
    return batch_service.update_batch(db, batch_id, data)


@router.delete("/{batch_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[WriteAccess])
def delete_batch(batch_id: int, db: DbSession) -> None:
    batch_service.delete_batch(db, batch_id)
