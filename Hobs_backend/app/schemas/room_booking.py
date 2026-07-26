# app/schemas/room_booking.py
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing import Optional
from uuid import UUID
from datetime import date, datetime
from decimal import Decimal

from app.models.room_booking import BookingStatus, BookingSource


class RoomBookingBase(BaseModel):
    room_id: UUID
    guest_name: Optional[str] = Field(None, max_length=100)
    guest_phone: Optional[str] = Field(None, max_length=20, example="2348012345678")
    check_in: date
    check_out: date

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="after")
    def check_out_after_check_in(self):
        if self.check_out <= self.check_in:
            raise ValueError("check_out must be after check_in")
        return self


class RoomBookingCreate(RoomBookingBase):
    merchant_id: str = Field(..., min_length=1, max_length=20)
    client_id: str = Field(..., min_length=1, max_length=20)
    source: BookingSource = BookingSource.GUEST_WHATSAPP
    logged_by_staff_phone: Optional[str] = None
    raw_staff_message: Optional[str] = None


class RoomBookingUpdate(BaseModel):
    guest_name: Optional[str] = None
    guest_phone: Optional[str] = None
    status: Optional[BookingStatus] = None

    model_config = ConfigDict(from_attributes=True)


class RoomBookingRead(RoomBookingBase):
    id: str
    booking_code: str
    merchant_id: str
    client_id: str
    total_amount: Decimal
    amount_paid: Optional[Decimal] = None
    status: BookingStatus
    source: BookingSource
    logged_by_staff_phone: Optional[str] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class RoomBookingAdminRead(RoomBookingRead):
    """Admin-level drill-down — full guest + audit detail. Front-desk role never gets this shape."""
    raw_staff_message: Optional[str] = None
    payment_ref: Optional[str] = None
    confirmed_at: Optional[datetime] = None
    checked_in_at: Optional[datetime] = None
    checked_out_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
