import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.exceptions.handlers import register_exception_handlers
from app.routes import alerts, batches, dashboard, health, products
from app.services.barcode_service import create_client

settings = get_settings()
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("ExpiryWatch starting (env=%s)", settings.app_env)
    # One shared client reuses connections. It stays unused unless a lookup is requested.
    async with create_client(settings.external_api_base_url) as client:
        app.state.barcode_client = client
        yield
    logger.info("ExpiryWatch shutting down")


app = FastAPI(title="ExpiryWatch", version="0.1.0", lifespan=lifespan)
register_exception_handlers(app)
app.include_router(health.router)
app.include_router(products.router, prefix="/api/v1")
app.include_router(batches.router, prefix="/api/v1")
app.include_router(alerts.router, prefix="/api/v1")
app.include_router(dashboard.router, prefix="/api/v1")
