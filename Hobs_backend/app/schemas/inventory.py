# app/schemas/inventory.py

from pydantic import BaseModel, ConfigDict
from typing import Optional
import uuid


class InventoryBase(BaseModel):
    product_id: uuid.UUID
    merchant_id: str
    client_id: str
    quantity: int
    unit_price: Optional[float] = None
    warehouse_location: Optional[str] = None


class InventoryCreate(InventoryBase):
    pass


class InventoryUpdate(BaseModel):
    quantity: Optional[int] = None
    unit_price: Optional[float] = None
    warehouse_location: Optional[str] = None


class InventoryOut(InventoryBase):
    id: uuid.UUID

    model_config = ConfigDict(from_attributes=True)