from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, CheckConstraint, Date, ForeignKey, Identity, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.product import Product


class InventoryBatch(TimestampMixin, Base):
    __tablename__ = "inventory_batches"
    __table_args__ = (CheckConstraint("quantity >= 0", name="quantity_non_negative"),)
    # A row already deleted by a concurrent request is the end state wanted, not an error.
    __mapper_args__ = {"confirm_deleted_rows": False}

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("products.id", ondelete="RESTRICT"), index=True
    )
    # Not unique: one batch number can legitimately sit in two locations.
    batch_number: Mapped[str | None] = mapped_column(String(64))
    quantity: Mapped[int] = mapped_column(Integer)
    # No status column: status is always derived from expiry_date and today.
    expiry_date: Mapped[date] = mapped_column(Date, index=True)
    # Set by the service so "today" has one definition (APP_TIMEZONE), not the database clock.
    received_at: Mapped[date] = mapped_column(Date)
    location: Mapped[str | None] = mapped_column(String(255))

    product: Mapped["Product"] = relationship(back_populates="batches")
