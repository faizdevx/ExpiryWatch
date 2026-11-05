from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator

from app.schemas.common import RequestModel, reject_null


def blank_to_none(value: object) -> object:
    return None if isinstance(value, str) and not value.strip() else value


Name = Annotated[str, Field(min_length=1, max_length=255)]
# EAN-8 to GTIN-14. Blank means no barcode, so it cannot trip the UNIQUE constraint.
Barcode = Annotated[
    # pattern goes on str alone: on the union with a BeforeValidator, None raises TypeError.
    Annotated[str, Field(pattern=r"^\d{8,14}$")] | None,
    BeforeValidator(blank_to_none),
]
OptionalLabel = Annotated[str | None, Field(max_length=255)]


class ProductCreate(RequestModel):
    name: Name
    barcode: Barcode = None
    brand: OptionalLabel = None
    category: OptionalLabel = None
    description: str | None = None


class ProductUpdate(RequestModel):
    name: Name | None = None
    barcode: Barcode = None
    brand: OptionalLabel = None
    category: OptionalLabel = None
    description: str | None = None

    _name_not_null = field_validator("name")(reject_null)


class ProductRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    barcode: str | None
    brand: str | None
    category: str | None
    description: str | None
    created_at: datetime
    updated_at: datetime
