from sqlalchemy import Column, String, Text, DateTime, Boolean, ForeignKey, func
from app.db.base import Base
from .utils import generate_uuid
import logging
logger = logging.getLogger(__name__)


class Clarification(Base):
    __tablename__ = "clarifications"

    id = Column(String(36), primary_key=True, index=True, default=generate_uuid)
    merchant_id = Column(
        String(20),
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
    )
    client_id = Column(
        String(20),
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=True,
    )
    session_id = Column(String, nullable=True)  # optional WhatsApp thread/session
    question = Column(Text, nullable=False)
    resolved = Column(Boolean, default=False, nullable=False)
    resolution = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)