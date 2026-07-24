# app/schemas/payment.py

from pydantic import BaseModel, ConfigDict
from typing import Optional, Dict, Any
from datetime import datetime
from app.models.payment import PaymentStatus


class PaymentBase(BaseModel):
    order_id: str
    merchant_id: str
    client_id: str
    amount: float
    method: str
    status: PaymentStatus = PaymentStatus.PENDING


class PaymentCreate(PaymentBase):
    metadata: Optional[Dict[str, Any]] = None


class PaymentRead(PaymentBase):
    id: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
