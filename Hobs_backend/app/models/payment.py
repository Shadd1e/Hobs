# app/models/payment.py

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

from app.db.base import Base
from .utils import generate_uuid


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

    id = Column(
        String(36),
        primary_key=True,
        index=True,
        default=generate_uuid,
    )

    order_id = Column(
        String(36),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    merchant_id = Column(
        String(20),
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    client_id = Column(
        String(20),
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    amount = Column(Numeric(12, 2), nullable=False)

    method = Column(String(50), nullable=False)

    status = Column(
        SAEnum(
            PaymentStatus,
            name="payment_status_enum",
            create_type=False,
        ),
        nullable=False,
        default=PaymentStatus.PENDING,
    )

    # Used for Flutterwave tx_ref or gateway reference
    external_reference = Column(
        String(128),
        unique=True,
        nullable=True,
    )

    # Stores provider data, tx_ref, webhook payloads etc.
    payment_metadata = Column(JSON, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    order = relationship("Order", lazy="select")
    merchant = relationship("Merchant", back_populates="payments")
    client = relationship("Client", back_populates="payments")