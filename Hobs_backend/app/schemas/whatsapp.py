import logging
logger = logging.getLogger(__name__)

# app/schemas/whatsapp.py
from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime


class WhatsAppMessageLogBase(BaseModel):
    merchant_id: str
    client_id: str
    from_number: str
    to_number: str
    direction: str  # "incoming" or "outgoing"
    message: str
    session_id: Optional[str] = None  # optional grouping identifier


class WhatsAppMessageLogCreate(WhatsAppMessageLogBase):
    """Used when creating a new WhatsApp message log."""
    pass


class WhatsAppMessageLogRead(WhatsAppMessageLogBase):
    """Used when returning WhatsApp message logs from DB."""
    id: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
