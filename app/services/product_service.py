import logging

from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.exceptions.handlers import ConflictError, NotFoundError
from app.models import InventoryBatch, Product
from app.schemas.product import ProductCreate, ProductUpdate

logger = logging.getLogger(__name__)


def _commit_product(db: Session, barcode: str | None) -> None:
    # Rely on the UNIQUE constraint: a check-then-insert would race with a concurrent request.
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        if error.orig.diag.constraint_name == "uq_products_barcode":
            raise ConflictError(
                "duplicate_barcode", f"A product with barcode {barcode} already exists"
            ) from error
        raise


def create_product(db: Session, data: ProductCreate) -> Product:
    product = Product(**data.model_dump())
    db.add(product)
    _commit_product(db, data.barcode)
    db.refresh(product)
    logger.info("Created product id=%s", product.id)
    return product


def get_product(db: Session, product_id: int) -> Product:
    product = db.get(Product, product_id)
    if product is None:
        raise NotFoundError("product", product_id)
    return product


def list_products(
    db: Session,
    *,
    q: str | None,
    category: str | None,
    brand: str | None,
    barcode: str | None,
    limit: int,
    offset: int,
) -> tuple[list[Product], int]:
    conditions = []
    if q:
        # autoescape: a search for "50%" means those characters, not a wildcard.
        conditions.append(
            or_(
                Product.name.icontains(q, autoescape=True),
                Product.brand.icontains(q, autoescape=True),
            )
        )
    if category:
        conditions.append(func.lower(Product.category) == category.lower())
    if brand:
        conditions.append(func.lower(Product.brand) == brand.lower())
    if barcode:
        conditions.append(Product.barcode == barcode)

    total = db.scalar(select(func.count()).select_from(Product).where(*conditions))
    query = select(Product).where(*conditions).order_by(Product.name, Product.id)
    return list(db.scalars(query.limit(limit).offset(offset))), total


def update_product(db: Session, product_id: int, data: ProductUpdate) -> Product:
    product = get_product(db, product_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(product, field, value)
    _commit_product(db, data.barcode)
    db.refresh(product)
    return product


def delete_product(db: Session, product_id: int) -> None:
    """Delete a product and its zero-quantity batches. Any stock left blocks the delete."""
    product = get_product(db, product_id)
    # Only quantity 0 is removed, so a batch restocked concurrently survives and the FK objects.
    db.execute(
        delete(InventoryBatch).where(
            InventoryBatch.product_id == product_id, InventoryBatch.quantity == 0
        )
    )
    db.delete(product)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise ConflictError(
            "product_has_stock",
            f"Product {product_id} still has stock. Delete its batches or set them to 0 first",
        ) from error
    logger.info("Deleted product id=%s", product_id)
