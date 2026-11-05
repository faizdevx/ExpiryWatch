from typing import Annotated

from fastapi import APIRouter, Query

from app.database import DbSession
from app.schemas.batch import BatchRead, batch_page
from app.schemas.common import Limit, Offset, Page
from app.services import batch_service
from app.services.expiry_service import Clock, ExpiryClock, ExpiryStatus

router = APIRouter(prefix="/alerts", tags=["alerts"])


# Every alert route is a FEFO list of batches with stock, narrowed to one expiry range.
@router.get("")
def all_alerts(
    db: DbSession, clock: Clock, limit: Limit = 50, offset: Offset = 0
) -> Page[BatchRead]:
    found = batch_service.list_batches(
        db, expiry_ranges=((None, clock.last_warning_day),), limit=limit, offset=offset
    )
    return batch_page(found, clock, limit, offset)


@router.get("/expired")
def expired_alerts(
    db: DbSession, clock: Clock, limit: Limit = 50, offset: Offset = 0
) -> Page[BatchRead]:
    found = batch_service.list_batches(
        db, expiry_ranges=(clock.bounds(ExpiryStatus.EXPIRED),), limit=limit, offset=offset
    )
    return batch_page(found, clock, limit, offset)


@router.get("/expiring")
def expiring_alerts(
    db: DbSession,
    clock: Clock,
    within_days: Annotated[int | None, Query(ge=0, le=3650)] = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> Page[BatchRead]:
    window = clock.warning_days if within_days is None else within_days
    query_clock = ExpiryClock(today=clock.today, warning_days=window)
    found = batch_service.list_batches(
        db,
        expiry_ranges=(query_clock.bounds(ExpiryStatus.EXPIRING_SOON),),
        limit=limit,
        offset=offset,
    )
    # Status still uses the configured window: within_days only widens the search.
    return batch_page(found, clock, limit, offset)
