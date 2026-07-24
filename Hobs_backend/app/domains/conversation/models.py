import uuid
import logging

from sqlalchemy import (
    Column, String, Text, DateTime, Boolean,
    ForeignKey, Float, Enum, Index, func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.infrastructure.db.base import Base
from app.shared.models import generate_uuid

logger = logging.getLogger(__name__)


class Clarification(Base):
    __tablename__ = "clarifications"

    id = Column(String(36), primary_key=True, index=True, default=generate_uuid)
    merchant_id = Column(String(6), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False)
    client_id = Column(String(6), ForeignKey("clients.id", ondelete="CASCADE"), nullable=True)
    session_id = Column(String, nullable=True)
    question = Column(Text, nullable=False)
    resolved = Column(Boolean, default=False, nullable=False)
    resolution = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class HumanAgent(Base):
    __tablename__ = "human_agent_tasks"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    cart_id = Column(UUID(as_uuid=True), ForeignKey("carts.id", ondelete="CASCADE"), nullable=False, index=True)
    client_id = Column(String(6), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    merchant_id = Column(String(6), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True)
    total_amount = Column(Float, nullable=False)
    status = Column(String, default="pending")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    cart = relationship("Cart", lazy="joined")
    merchant = relationship("Merchant", back_populates="human_agent_tasks")
    client = relationship("Client", back_populates="human_agent_tasks")


class WebhookEvent(Base):
    __tablename__ = "webhook_events"

    id = Column(String(128), primary_key=True)
    provider = Column(String(50), nullable=False, index=True)
    merchant_id = Column(String(6), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True)
    client_id = Column(String(6), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    phone_number_id = Column(String(255), nullable=True, index=True)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_webhook_provider_client", "provider", "client_id"),
    )


class WhatsappMessageLog(Base):
    __tablename__ = "whatsapp_message_logs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    merchant_id = Column(String, nullable=False)
    client_id = Column(String, nullable=True)
    from_number = Column(String, nullable=False)
    to_number = Column(String, nullable=True)
    direction = Column(
        Enum("incoming", "outgoing", name="whatsapp_message_direction"),
        nullable=False,
    )
    message = Column(Text, nullable=True)
    meta = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
