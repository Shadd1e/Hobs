# app/schemas/cart.py

from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime
import uuid


class CartItemSchema(BaseModel):
    product_id: uuid.UUID
    quantity: int = Field(..., gt=0)
    price_at_add: float = Field(..., ge=0)

    model_config = ConfigDict(from_attributes=True)


class CartSchema(BaseModel):
    id: uuid.UUID
    merchant_id: str = Field(..., min_length=6, max_length=6)
    client_id: str = Field(..., min_length=6, max_length=6)
    user_id: str

    created_at: datetime
    checked_out: bool
    checked_out_at: Optional[datetime] = None

    items: List[CartItemSchema] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class CartAddItem(BaseModel):
    merchant_id: str
    client_id: str
    user_id: str
    product_id: uuid.UUID
    quantity: int = Field(..., gt=0)
    price_at_add: float = Field(..., ge=0)


class CartRemoveItem(BaseModel):
    merchant_id: str
    client_id: str
    user_id: str
    product_id: uuid.UUID
    quantity: int = Field(..., gt=0)