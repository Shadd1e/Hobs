import logging
logger = logging.getLogger(__name__)

# app/schemas/whatsapp_message_log.py
from pydantic import BaseModel, ConfigDict, StringConstraints, constr, field_validator, model_validator
from typing import Annotated, Optional
from datetime import datetime

MerchantID = Annotated[str, StringConstraints(pattern=r'^MX[A-Z0-9]{6}$')]
ClientID = Annotated[str, StringConstraints(pattern=r'^ST[A-Z0-9]{6}$')]

class WhatsAppMessageLogBase(BaseModel):
    merchant_id: MerchantID
    client_id: Optional[ClientID] = None
    from_number: str
    to_number: Optional[str] = None
    direction: str   # "incoming" or "outgoing"
    message: Optional[str] = None
    meta: Optional[str] = None

class WhatsAppMessageLogCreate(WhatsAppMessageLogBase):
    pass

class WhatsAppMessageLogRead(WhatsAppMessageLogBase):
    id: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
