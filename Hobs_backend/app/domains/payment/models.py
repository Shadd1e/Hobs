from sqlalchemy import (
    Column,
    String,
    DateTime,
    ForeignKey,
    func,
    UniqueConstraint,
    Enum as SAEnum,
    Numeric,
    Index,
)
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import relationship
from enum import Enum

from app.infrastructure.db.base import Base
from app.shared.models import generate_uuid


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"


class Payment(Base):
    __tablename__ = "payments"

    __table_args__ = (
        UniqueConstraint("order_id", name="uq_payment_per_order"),
        Index("ix_payment_external_reference", "external_reference"),
        Index("ix_payment_merchant_client", "merchant_id", "client_id"),
    )

    id = Column(String(36), primary_key=True, index=True, default=generate_uuid)

    order_id = Column(
        String(36),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    merchant_id = Column(String(6), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True)
    client_id = Column(String(6), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)

    amount = Column(Numeric(12, 2), nullable=False)
    method = Column(String(50), nullable=False)

    status = Column(
        SAEnum(PaymentStatus, name="payment_status_enum"),
        nullable=False,
        default=PaymentStatus.PENDING,
    )

    # Flutterwave tx_ref / external provider reference
    external_reference = Column(String(128), unique=True, nullable=True)

    # Arbitrary provider metadata (Flutterwave payload, timestamps, etc.)
    payment_metadata = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    order = relationship("Order", back_populates="payments", lazy="joined")
    merchant = relationship("Merchant", back_populates="payments")
    client = relationship("Client", back_populates="payments")
