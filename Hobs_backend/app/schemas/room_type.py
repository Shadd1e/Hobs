# app/schemas/room_type.py
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Optional
from uuid import UUID
from urllib.parse import urlparse


class RoomTypeBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, example="Deluxe Room")
    description: Optional[str] = Field(None, example="Queen bed, en-suite bathroom, AC, city view")
    price: float = Field(..., gt=0, example=25000.00, description="Flat nightly rate")
    image_url: Optional[str] = Field(None, example="https://example.com/deluxe.jpg")
    merchant_id: Optional[str] = Field(None, min_length=1, max_length=20, example="MRC001")
    client_id: Optional[str] = Field(None, min_length=1, max_length=20, example="HT0001")

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
                raise ValueError("image_url points to a blocked/private host")
        return v


class RoomTypeCreate(RoomTypeBase):
    merchant_id: str = Field(..., min_length=1, max_length=20)
    client_id: str = Field(..., min_length=1, max_length=20)


class RoomTypeUpdate(BaseModel):
    """All fields optional — admin can adjust price without resubmitting everything, same as ProductUpdate."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    price: Optional[float] = Field(None, gt=0)
    image_url: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class RoomTypeRead(RoomTypeBase):
    id: UUID
    model_config = ConfigDict(from_attributes=True)
