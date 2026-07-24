from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel, ConfigDict, Field
import logging

logger = logging.getLogger(__name__)


# ================================
# Base Schema
# ================================
class IdempotencyBase(BaseModel):
    merchant_id: str
    key: str

    model_config = ConfigDict(from_attributes=True)


# ================================
# Stored Record Schema (Full DB View)
# ================================
class IdempotencyRecordSchema(IdempotencyBase):
    id: str
    request_hash: Optional[str] = None

    response_data: Optional[Dict[str, Any]] = None
    response_status: Optional[int] = None
    response_headers: Optional[Dict[str, Any]] = None

    is_processing: bool

    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None


# ================================
# Public Cached Response Schema
# (What you return from cache)
# ================================
class IdempotencyCachedResponse(BaseModel):
    data: Dict[str, Any]
    status: int
    headers: Dict[str, Any]

    model_config = ConfigDict(from_attributes=True)