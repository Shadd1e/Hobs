# app/schemas/order.py

from pydantic import BaseModel, field_validator
from typing import Optional
from datetime import datetime
from enum import Enum
import uuid


# =====================================================
# ORDER STATUS ENUM (MUST MATCH DB + MODEL EXACTLY)
# =====================================================
class OrderStatus(str, Enum):
    CREATED          = "CREATED"
    PENDING_PAYMENT  = "PENDING_PAYMENT"
    PAID             = "PAID"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"   # delivery orders in transit
    AWAITING_PICKUP  = "AWAITING_PICKUP"
    FULFILLED        = "FULFILLED"
    CANCELLED        = "CANCELLED"
    REFUNDED         = "REFUNDED"


# =====================================================
# BASE ORDER RESPONSE STRUCTURE
# =====================================================
class OrderRead(BaseModel):
    id: str
    order_code: str

    merchant_id: str
    client_id: str
    user_id: str

    customer_name: Optional[str] = None
    payment_method: str

    total_amount: float
    status: OrderStatus

    created_at: Optional[datetime] = None
    confirmed_at: Optional[datetime] = None
    fulfilled_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None

    model_config = {
        "from_attributes": True
    }
