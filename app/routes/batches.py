from datetime import date

from fastapi import APIRouter, status

from app.auth import WriteAccess
from app.database import DbSession
from app.schemas.batch import BatchCreate, BatchRead, BatchUpdate, batch_page
from app.schemas.common import Limit, Offset, Page
from app.services import batch_service
from app.services.batch_service import BatchSort
from app.services.expiry_service import Clock, ExpiryStatus

router = APIRouter(prefix="/batches", tags=["batches"])


@router.post("", status_code=status.HTTP_201_CREATED, dependencies=[WriteAccess])
def create_batch(data: BatchCreate, db: DbSession, clock: Clock) -> BatchRead:
    return BatchRead.build(batch_service.create_batch(db, data, clock.today), clock)


@router.get("")
def list_batches(
    db: DbSession,
    clock: Clock,
    product_id: int | None = None,
    expiry_status: ExpiryStatus | None = None,
    location: str | None = None,
    expiry_from: date | None = None,
    expiry_to: date | None = None,
    include_depleted: bool = False,
    sort: BatchSort = "expiry_asc",
    limit: Limit = 50,
    offset: Offset = 0,
) -> Page[BatchRead]:
    ranges = [(expiry_from, expiry_to)]
    if expiry_status:
        ranges.append(clock.bounds(expiry_status))
    found = batch_service.list_batches(
        db,
        product_id=product_id,
        location=location,
        expiry_ranges=tuple(ranges),
        include_depleted=include_depleted,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    return batch_page(found, clock, limit, offset)


@router.get("/{batch_id}")
def get_batch(batch_id: int, db: DbSession, clock: Clock) -> BatchRead:
    return BatchRead.build(batch_service.get_batch(db, batch_id), clock)


@router.patch("/{batch_id}", dependencies=[WriteAccess])
def update_batch(batch_id: int, data: BatchUpdate, db: DbSession, clock: Clock) -> BatchRead:
    return BatchRead.build(batch_service.update_batch(db, batch_id, data), clock)


@router.delete("/{batch_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[WriteAccess])
def delete_batch(batch_id: int, db: DbSession) -> None:
    batch_service.delete_batch(db, batch_id)
