# app/schemas/room.py
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional
from uuid import UUID
from datetime import date


class RoomBase(BaseModel):
    room_number: str = Field(..., min_length=1, max_length=20, example="12B")
    room_type_id: UUID
    is_active: bool = True

    model_config = ConfigDict(from_attributes=True)


class RoomCreate(RoomBase):
    merchant_id: str = Field(..., min_length=1, max_length=20)
    client_id: str = Field(..., min_length=1, max_length=20)


class RoomUpdate(BaseModel):
    room_number: Optional[str] = Field(None, min_length=1, max_length=20)
    room_type_id: Optional[UUID] = None
    is_active: Optional[bool] = None

    model_config = ConfigDict(from_attributes=True)


class RoomRead(RoomBase):
    id: UUID
    merchant_id: str
    client_id: str
    model_config = ConfigDict(from_attributes=True)


class RoomAvailabilityQuery(BaseModel):
    """Used by the guest bot and the dashboard to check a date range."""
    check_in: date
    check_out: date
    room_type_id: Optional[UUID] = None


class RoomStatusRead(RoomBase):
    """
    What the dashboard grid shows. Per the earlier product decision:
    starter/front-desk view only shows free/booked; the admin drill-down
    (guest name, dates, logged_by) is a separate, permission-gated endpoint.
    """
    id: UUID
    is_booked_today: bool
    room_type_name: str
    room_type_price: float
    model_config = ConfigDict(from_attributes=True)
