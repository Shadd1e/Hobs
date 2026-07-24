import logging
logger = logging.getLogger(__name__)

# app/schemas/product.py
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Optional
from uuid import UUID
from datetime import datetime
from urllib.parse import urlparse


# -----------------------------
# Base Schema (shared)
# -----------------------------
class ProductBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, example="Indomie Chicken Noodles")
    description: Optional[str] = Field(None, example="Instant noodles, 70g pack")
    price: float = Field(..., gt=0, example=120.00)
    category: Optional[str] = Field(None, example="Food")
    image_url: Optional[str] = Field(None, example="https://example.com/image.jpg")
    merchant_id: Optional[str] = Field(None, min_length=1, max_length=10, example="MRC001")
    client_id: Optional[str] = Field(None, min_length=1, max_length=10, example="CLT001")

    model_config = ConfigDict(from_attributes=True)

    @field_validator("image_url", mode="before")
    @classmethod
    def validate_image_url(cls, v):
        if not v:
            return v
        try:
            parsed = urlparse(str(v))
        except Exception:
            raise ValueError("Invalid image URL")
        if parsed.scheme not in ("http", "https"):
            raise ValueError("image_url must use http or https")
        host = parsed.hostname or ""
        blocked = ("169.254.", "10.", "192.168.", "127.", "0.0.0.0")
        for prefix in blocked:
            if host.startswith(prefix):
                raise ValueError("image_url points to a restricted address")
        if host.startswith("172."):
            try:
                second_octet = int(host.split(".")[1])
                if 16 <= second_octet <= 31:
                    raise ValueError("image_url points to a restricted address")
            except (IndexError, ValueError):
                pass
        return v


# -----------------------------
# Create Schema
# -----------------------------
class ProductCreate(ProductBase):
    id: Optional[UUID] = None
    initial_stock: int = Field(0, ge=0, description="Starting inventory quantity")


# -----------------------------
# Update Schema
# -----------------------------
class ProductUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    price: Optional[float] = Field(None, gt=0)
    category: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# -----------------------------
# Read Schema
# -----------------------------
class InventoryInfo(BaseModel):
    """Embedded inventory snapshot on ProductRead."""
    quantity: int = 0
    low_stock_threshold: Optional[int] = None
    model_config = ConfigDict(from_attributes=True)


class ProductRead(ProductBase):
    id: UUID
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    inventory: Optional[InventoryInfo] = None

    model_config = ConfigDict(from_attributes=True)


# -----------------------------
# Search Result Schema
# -----------------------------
class ProductSearchResult(BaseModel):
    product: ProductRead
    score: float

    model_config = ConfigDict(from_attributes=True)
