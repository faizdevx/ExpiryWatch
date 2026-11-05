from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Identity, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.batch import InventoryBatch


class Product(TimestampMixin, Base):
    __tablename__ = "products"
    # A row already deleted by a concurrent request is the end state wanted, not an error.
    __mapper_args__ = {"confirm_deleted_rows": False}

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    # Postgres treats NULLs as distinct, so many products can have no barcode.
    barcode: Mapped[str | None] = mapped_column(String(14), unique=True)
    brand: Mapped[str | None] = mapped_column(String(255))
    category: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)

    # passive_deletes="all" stops the ORM nulling product_id, so the FK RESTRICT decides.
    batches: Mapped[list["InventoryBatch"]] = relationship(
        back_populates="product", passive_deletes="all"
    )
