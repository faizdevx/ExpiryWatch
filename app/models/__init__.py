# Importing the models registers them on Base.metadata, which Alembic reads.
from app.models.batch import InventoryBatch
from app.models.product import Product

__all__ = ["InventoryBatch", "Product"]
