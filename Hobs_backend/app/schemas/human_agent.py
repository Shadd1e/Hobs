import logging
logger = logging.getLogger(__name__)

# app/schemas/human_agent.py

from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class HumanAgentBase(BaseModel):
    order_id: str
    cart_id: str
    merchant_id: str
    client_id: str
    total_amount: float


class HumanAgentCreate(HumanAgentBase):
    """
    Payload used when escalating a checkout
    to a human agent (cash / manual payment).
    """
    pass


class HumanAgentRead(HumanAgentBase):
    id: str
    status: str
    assigned_agent: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
