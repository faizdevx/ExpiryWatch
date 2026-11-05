from fastapi import APIRouter

from app.database import DbSession
from app.schemas.batch import DashboardSummary
from app.services.expiry_service import Clock, get_summary

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary")
def summary(db: DbSession, clock: Clock) -> DashboardSummary:
    return DashboardSummary(**get_summary(db, clock))
