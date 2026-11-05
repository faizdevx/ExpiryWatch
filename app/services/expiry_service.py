from datetime import date, datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import Depends

from app.config import Settings, get_settings


def get_today(settings: Annotated[Settings, Depends(get_settings)]) -> date:
    """The single definition of "today". Tests override this dependency to fix the date."""
    return datetime.now(ZoneInfo(settings.app_timezone)).date()


Today = Annotated[date, Depends(get_today)]
