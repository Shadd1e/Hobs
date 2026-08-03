from sqlalchemy import Column, String, DateTime, Integer, Boolean, func
from sqlalchemy.orm import relationship
from app.db.base import Base
import logging

logger = logging.getLogger(__name__)


class Merchant(Base):
    __tablename__ = "merchants"

    id                               = Column(String(20),   primary_key=True, index=True)
    name                             = Column(String(255), nullable=False)
    email                            = Column(String(255), unique=True, nullable=False)
    password_hash                    = Column(String(255), nullable=False)
    failed_attempts                  = Column(Integer,     default=0, nullable=False)
    email_verified                   = Column(Boolean,     default=False, nullable=False)
    must_change_password             = Column(
        Boolean, default=False, nullable=False,
        comment="Set True when an account is created by admin with a generated password. "
                "Cleared on first successful password reset. Prevents use of the "
                "auto-generated initial password indefinitely.",
    )
    email_verification_token         = Column(String(64),  nullable=True, index=True)
    email_verification_token_expiry  = Column(DateTime(timezone=True), nullable=True)
    waba_active                      = Column(Boolean,     default=False, nullable=False)

    # WhatsApp number submitted at registration — stored without + prefix
    # e.g. "2348012345678". Lets the admin dashboard show the number
    # without joining through clients.
    whatsapp_number = Column(
        String(20),
        nullable=True,
        comment="WhatsApp number submitted at registration (no + prefix)",
    )

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Set by an admin (POST /admin/whatsapp-setup/merchants/{id}/suspend-messaging)
    # when a merchant still hasn't submitted NIN/CAC verification well past the
    # 7-day grace period. Blocks outbound WhatsApp messaging only — everything
    # else (dashboard, orders, payments) keeps working. Cleared the moment the
    # merchant submits verification, or by an admin manually unsuspending.
    messaging_suspended_at = Column(
        DateTime(timezone=True), nullable=True,
        comment="Non-null = outbound WhatsApp messaging is blocked for this merchant.",
    )

    # ── Relationships ──────────────────────────────────────────────────
    clients = relationship(
        "Client",
        back_populates="merchant",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    products = relationship(
        "Product",
        back_populates="merchant",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    carts = relationship(
        "Cart",
        back_populates="merchant",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    payments = relationship(
        "Payment",
        back_populates="merchant",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    orders = relationship(
        "Order",
        back_populates="merchant",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    inventories = relationship(
        "Inventory",
        back_populates="merchant",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    human_agent_tasks = relationship(
        "HumanAgent",
        back_populates="merchant",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    # ── Hotel domain (HoBS) ──────────────────────────────────────────────
    room_types = relationship(
        "RoomType",
        back_populates="merchant",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    rooms = relationship(
        "Room",
        back_populates="merchant",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    room_bookings = relationship(
        "RoomBooking",
        back_populates="merchant",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    hotel_staff = relationship(
        "HotelStaff",
        back_populates="merchant",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    # ── Helper properties ──────────────────────────────────────────────
    @property
    def all_whatsapp_credentials(self):
        """All WhatsApp credentials across all stores for this merchant."""
        credentials = []
        for client in self.clients:
            if client.whatsapp_credential:
                credentials.append(client.whatsapp_credential)
        return credentials

    @property
    def active_whatsapp_credentials(self):
        """Only credentials that are fully live (status='active')."""
        return [c for c in self.all_whatsapp_credentials if c.status == "active"]

    def __repr__(self):
        return f"<Merchant(id={self.id}, name={self.name}, email={self.email})>"
