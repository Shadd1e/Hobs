# app/models/hotel_staff.py
from sqlalchemy import Column, String, DateTime, ForeignKey, Boolean, func, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid
from app.db.base import Base
import logging

logger = logging.getLogger(__name__)


class HotelStaff(Base):
    """
    A staff phone number authorized to text booking updates into the
    system for a given hotel. Has no ShoprHQ equivalent — ShoprHQ's
    `operator_notify_phone` on Client is outbound-only (system -> operator).
    This is the new inbound side: whatsapp_handler checks incoming
    messages against this table (by client_id + phone_number) to decide
    whether to route a message through the guest conversation flow or the
    staff booking-update flow.

    Also doubles as the login identity for dashboard access, per the
    "WhatsApp + dashboard login" decision — password_hash is nullable
    because a staff member might be WhatsApp-only with no dashboard
    account at all.
    """
    __tablename__ = "hotel_staff"

    __table_args__ = (
        UniqueConstraint("client_id", "phone_number", name="uq_staff_phone_per_hotel"),
        Index("ix_hotel_staff_phone", "phone_number"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    name = Column(String(100), nullable=True)

    phone_number = Column(
        String(20), nullable=False,
        comment="WhatsApp number, no + prefix, e.g. '2348012345678'. Matched against inbound webhook sender.",
    )

    role = Column(
        String(20), nullable=False, default="front_desk",
        comment="front_desk | manager | admin — admin can see full guest details in the dashboard drill-down, front_desk sees status only.",
    )

    # Dashboard login — optional, per staff member.
    password_hash = Column(String(255), nullable=True)

    is_active = Column(Boolean, default=True, nullable=False)

    # ── Foreign keys ───────────────────────────────────────────────────────────
    merchant_id = Column(String(20), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True)
    client_id   = Column(String(20), ForeignKey("clients.id",   ondelete="CASCADE"), nullable=False, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # ── Relationships ──────────────────────────────────────────────────────────
    merchant = relationship("Merchant", back_populates="hotel_staff")
    client   = relationship("Client",   back_populates="hotel_staff")

    def __repr__(self):
        return f"<HotelStaff(id={self.id}, phone={self.phone_number!r}, role={self.role!r})>"
