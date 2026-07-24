from sqlalchemy import Column, String, Float, DateTime, Boolean, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base import Base
from .utils import generate_uuid
import logging
logger = logging.getLogger(__name__)


class HumanAgent(Base):
    __tablename__ = "human_agent_tasks"

    id = Column(String(36), primary_key=True, default=generate_uuid)

    # FIX: match Cart.id type (UUID)
    cart_id = Column(UUID(as_uuid=True), ForeignKey("carts.id", ondelete="CASCADE"), nullable=False, index=True)

    client_id = Column(String(20), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    merchant_id = Column(String(20), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True)

    total_amount = Column(Float, nullable=False)
    status = Column(String, default="pending")  # pending, completed, cancelled
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    cart = relationship("Cart", lazy="joined")
    merchant = relationship("Merchant", back_populates="human_agent_tasks")
    client = relationship("Client", back_populates="human_agent_tasks")