from datetime import date, datetime
from typing import Annotated, Self

from pydantic import BaseModel, Field, field_validator

from app.models import InventoryBatch
from app.schemas.common import Page, RequestModel, reject_null
from app.services.expiry_service import ExpiryClock, ExpiryStatus

# Upper bound is the Postgres integer limit, so an oversized value fails validation, not SQL.
Quantity = Annotated[int, Field(ge=0, le=2_147_483_647)]
BatchNumber = Annotated[str | None, Field(max_length=64)]
Location = Annotated[str | None, Field(max_length=255)]


class BatchCreate(RequestModel):
    product_id: int = Field(ge=1)
    batch_number: BatchNumber = None
    quantity: Quantity
    expiry_date: date  # Past dates are valid: already-expired stock must be recordable.
    received_at: date | None = None  # Defaults to today in the service.
    location: Location = None


class BatchUpdate(RequestModel):
    # No product_id: a batch cannot move to another product.
    batch_number: BatchNumber = None
    quantity: Quantity | None = None
    expiry_date: date | None = None
    received_at: date | None = None
    location: Location = None

    _required_not_null = field_validator("quantity", "expiry_date", "received_at")(reject_null)


class BatchRead(BaseModel):
    id: int
    product_id: int
    product_name: str
    batch_number: str | None
    quantity: int
    expiry_date: date
    received_at: date
    location: str | None
    status: ExpiryStatus
    days_until_expiry: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def build(cls, batch: InventoryBatch, clock: ExpiryClock) -> Self:
        # Derived on every read, never stored, so a status can never go stale in the database.
        return cls(
            id=batch.id,
            product_id=batch.product_id,
            product_name=batch.product.name,
            batch_number=batch.batch_number,
            quantity=batch.quantity,
            expiry_date=batch.expiry_date,
            received_at=batch.received_at,
            location=batch.location,
            status=clock.classify(batch.expiry_date),
            days_until_expiry=(batch.expiry_date - clock.today).days,
            created_at=batch.created_at,
            updated_at=batch.updated_at,
        )


def batch_page(
    found: tuple[list[InventoryBatch], int], clock: ExpiryClock, limit: int, offset: int
) -> Page[BatchRead]:
    batches, total = found
    return Page[BatchRead](
        items=[BatchRead.build(batch, clock) for batch in batches],
        total=total,
        limit=limit,
        offset=offset,
    )


class DashboardSummary(BaseModel):
    total_products: int
    total_active_batches: int
    total_units: int
    expired_batches: int
    expiring_soon_batches: int
    expired_units: int
    expiring_soon_units: int
