import logging
from datetime import date
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.exceptions.handlers import NotFoundError
from app.models import InventoryBatch
from app.schemas.batch import BatchCreate, BatchUpdate

logger = logging.getLogger(__name__)

BatchSort = Literal["expiry_asc", "expiry_desc"]
ExpiryRange = tuple[date | None, date | None]


def create_batch(db: Session, data: BatchCreate, today: date) -> InventoryBatch:
    values = data.model_dump()
    values["received_at"] = data.received_at or today
    batch = InventoryBatch(**values)
    db.add(batch)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        if error.orig.diag.constraint_name == "fk_inventory_batches_product_id_products":
            raise NotFoundError("product", data.product_id) from error
        raise
    db.refresh(batch)
    logger.info(
        "Created batch id=%s product_id=%s quantity=%s expiry_date=%s",
        batch.id,
        batch.product_id,
        batch.quantity,
        batch.expiry_date,
    )
    return batch


def get_batch(db: Session, batch_id: int) -> InventoryBatch:
    batch = db.get(InventoryBatch, batch_id)
    if batch is None:
        raise NotFoundError("batch", batch_id)
    return batch


def list_batches(
    db: Session,
    *,
    limit: int,
    offset: int,
    product_id: int | None = None,
    location: str | None = None,
    expiry_ranges: tuple[ExpiryRange, ...] = (),
    include_depleted: bool = False,
    sort: BatchSort = "expiry_asc",
) -> tuple[list[InventoryBatch], int]:
    """Filter batches. A batch must fall inside every range in expiry_ranges."""
    conditions = []
    if not include_depleted:
        conditions.append(InventoryBatch.quantity > 0)
    if product_id is not None:
        conditions.append(InventoryBatch.product_id == product_id)
    if location:
        conditions.append(func.lower(InventoryBatch.location) == location.lower())
    for earliest, latest in expiry_ranges:
        if earliest:
            conditions.append(InventoryBatch.expiry_date >= earliest)
        if latest:
            conditions.append(InventoryBatch.expiry_date <= latest)

    expiry_order = (
        InventoryBatch.expiry_date.asc()
        if sort == "expiry_asc"
        else InventoryBatch.expiry_date.desc()
    )
    # id breaks ties: same-day batches keep one order, so pages never repeat or skip a row.
    query = (
        select(InventoryBatch)
        .options(joinedload(InventoryBatch.product))  # Avoids one extra query per batch.
        .where(*conditions)
        .order_by(expiry_order, InventoryBatch.id)
    )
    total = db.scalar(select(func.count()).select_from(InventoryBatch).where(*conditions))
    return list(db.scalars(query.limit(limit).offset(offset))), total


def update_batch(db: Session, batch_id: int, data: BatchUpdate) -> InventoryBatch:
    batch = get_batch(db, batch_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(batch, field, value)
    db.commit()
    db.refresh(batch)
    logger.info("Updated batch id=%s quantity=%s", batch.id, batch.quantity)
    return batch


def delete_batch(db: Session, batch_id: int) -> None:
    db.delete(get_batch(db, batch_id))
    db.commit()
    logger.info("Deleted batch id=%s", batch_id)
