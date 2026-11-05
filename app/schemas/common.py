from typing import Annotated

from fastapi import Query
from pydantic import BaseModel, ConfigDict

Limit = Annotated[int, Query(ge=1, le=200)]
Offset = Annotated[int, Query(ge=0)]


class RequestModel(BaseModel):
    # forbid: a typo or an attempt to set product_id on PATCH fails instead of being ignored.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Page[Item](BaseModel):
    items: list[Item]
    total: int
    limit: int
    offset: int


def reject_null[Value](value: Value | None) -> Value:
    """On PATCH, omitting a required field is fine but sending null for it is not."""
    if value is None:
        raise ValueError("cannot be null")
    return value
