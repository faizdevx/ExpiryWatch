from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import RequestModel, reject_null

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
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    batch_number: str | None
    quantity: int
    expiry_date: date
    received_at: date
    location: str | None
    created_at: datetime
    updated_at: datetime
