from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import InventoryBatch, Product


class ExpiryStatus(StrEnum):
    EXPIRED = "EXPIRED"
    EXPIRING_SOON = "EXPIRING_SOON"
    SAFE = "SAFE"


def get_today(settings: Annotated[Settings, Depends(get_settings)]) -> date:
    """The single definition of "today". Tests override this dependency to fix the date."""
    return datetime.now(ZoneInfo(settings.app_timezone)).date()


@dataclass(frozen=True)
class ExpiryClock:
    """Status rules for one request, so every batch in a response is judged by the same day."""

    today: date
    warning_days: int

    @property
    def last_warning_day(self) -> date:
        return self.today + timedelta(days=self.warning_days)

    def classify(self, expiry_date: date) -> ExpiryStatus:
        if expiry_date < self.today:
            return ExpiryStatus.EXPIRED
        if expiry_date <= self.last_warning_day:
            return ExpiryStatus.EXPIRING_SOON
        return ExpiryStatus.SAFE

    def bounds(self, status: ExpiryStatus) -> tuple[date | None, date | None]:
        """The inclusive expiry_date range for a status, for SQL. Must agree with classify()."""
        return {
            ExpiryStatus.EXPIRED: (None, self.today - timedelta(days=1)),
            ExpiryStatus.EXPIRING_SOON: (self.today, self.last_warning_day),
            ExpiryStatus.SAFE: (self.last_warning_day + timedelta(days=1), None),
        }[status]


def get_expiry_clock(
    today: Annotated[date, Depends(get_today)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ExpiryClock:
    return ExpiryClock(today=today, warning_days=settings.expiry_warning_days)


Clock = Annotated[ExpiryClock, Depends(get_expiry_clock)]


def get_summary(db: Session, clock: ExpiryClock) -> dict[str, int]:
    quantity = InventoryBatch.quantity
    expiry = InventoryBatch.expiry_date
    active = quantity > 0
    expired = expiry < clock.today
    expiring = expiry.between(clock.today, clock.last_warning_day)

    # One query: SUM only ever adds active rows' quantity, since depleted batches hold 0.
    row = db.execute(
        select(
            func.count().filter(active).label("total_active_batches"),
            func.coalesce(func.sum(quantity), 0).label("total_units"),
            func.count().filter(active, expired).label("expired_batches"),
            func.count().filter(active, expiring).label("expiring_soon_batches"),
            func.coalesce(func.sum(quantity).filter(expired), 0).label("expired_units"),
            func.coalesce(func.sum(quantity).filter(expiring), 0).label("expiring_soon_units"),
        )
    ).one()
    total_products = db.scalar(select(func.count()).select_from(Product))
    return {"total_products": total_products, **row._mapping}
