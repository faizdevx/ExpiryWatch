from secrets import compare_digest
from typing import Annotated

from fastapi import Depends, Header

from app.config import Settings, get_settings
from app.exceptions.handlers import UnauthorizedError


def require_api_key(
    settings: Annotated[Settings, Depends(get_settings)],
    x_api_key: Annotated[str | None, Header()] = None,
) -> None:
    # No key configured is only possible outside production: Settings refuses it there.
    if settings.app_api_key is None:
        return
    expected = settings.app_api_key.get_secret_value()
    # Bytes, because compare_digest raises TypeError on non-ASCII str.
    if x_api_key is None or not compare_digest(x_api_key.encode(), expected.encode()):
        raise UnauthorizedError


WriteAccess = Depends(require_api_key)
