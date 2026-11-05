import logging
from datetime import date
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.exceptions.handlers import NotFoundError
from app.models import InventoryBatch
from app.schemas.batch import BatchCreate, BatchUpdate

logger = logging.getLogger(__name__)

BatchSort = Literal["expiry_asc", "expiry_desc"]


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
    return batch


def get_batch(db: Session, batch_id: int) -> InventoryBatch:
    batch = db.get(InventoryBatch, batch_id)
    if batch is None:
        raise NotFoundError("batch", batch_id)
    return batch


def list_batches(
    db: Session,
    *,
    product_id: int | None,
    location: str | None,
    expiry_from: date | None,
    expiry_to: date | None,
    include_depleted: bool,
    sort: BatchSort,
    limit: int,
    offset: int,
) -> tuple[list[InventoryBatch], int]:
    conditions = []
    if not include_depleted:
        conditions.append(InventoryBatch.quantity > 0)
    if product_id is not None:
        conditions.append(InventoryBatch.product_id == product_id)
    if location:
        conditions.append(func.lower(InventoryBatch.location) == location.lower())
    if expiry_from:
        conditions.append(InventoryBatch.expiry_date >= expiry_from)
    if expiry_to:
        conditions.append(InventoryBatch.expiry_date <= expiry_to)

    expiry_order = (
        InventoryBatch.expiry_date.asc()
        if sort == "expiry_asc"
        else InventoryBatch.expiry_date.desc()
    )
    # id breaks ties: same-day batches keep one order, so pages never repeat or skip a row.
    query = select(InventoryBatch).where(*conditions).order_by(expiry_order, InventoryBatch.id)
    total = db.scalar(select(func.count()).select_from(InventoryBatch).where(*conditions))
    return list(db.scalars(query.limit(limit).offset(offset))), total


def update_batch(db: Session, batch_id: int, data: BatchUpdate) -> InventoryBatch:
    batch = get_batch(db, batch_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(batch, field, value)
    db.commit()
    db.refresh(batch)
    return batch


def delete_batch(db: Session, batch_id: int) -> None:
    db.delete(get_batch(db, batch_id))
    db.commit()
    logger.info("Deleted batch id=%s", batch_id)
