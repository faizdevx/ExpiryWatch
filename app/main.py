import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.routes import health

settings = get_settings()
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logger.info("ExpiryWatch starting (env=%s)", settings.app_env)
    yield
    logger.info("ExpiryWatch shutting down")


app = FastAPI(title="ExpiryWatch", version="0.1.0", lifespan=lifespan)
app.include_router(health.router)
