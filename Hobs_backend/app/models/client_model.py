# app/models/client_model.py
from sqlalchemy import (
    Column, String, DateTime, ForeignKey, func, text,
    Boolean, Numeric, CheckConstraint, Integer,
)
from sqlalchemy.orm import relationship
from app.db.base import Base
import logging

logger = logging.getLogger(__name__)


# Valid values for assistant_personality — stored as plain strings so no enum
# migration is needed if we add more styles later.
PERSONALITY_CHOICES = frozenset({
    "friendly_casual",
    "professional",
    "warm_enthusiastic",
})


class Client(Base):
    __tablename__ = "clients"

    # ── Primary key ────────────────────────────────────────────────────────────
    id      = Column(String(length=20), primary_key=True, index=True)
    name    = Column(String, nullable=False)

    # Store address shown on PDF receipts
    address = Column(String, nullable=True)

    # ── Store-scoped login ─────────────────────────────────────────────────────
    # Argon2 hash of the store's dashboard password, set by the merchant.
    # Nullable — the first auto-created store starts without one.
    password_hash = Column(String(255), nullable=True)

    # ── WhatsApp / contact numbers ─────────────────────────────────────────────
    # Customer-facing WhatsApp number — nullable until merchant connects one
    whatsapp_number = Column(String(20), nullable=True)

    # Store confirmation / pickup authorisation number
    store_contact_number = Column(String(20), nullable=True)

    # Operator WhatsApp number for order/payment notifications
    operator_notify_phone = Column(String(20), nullable=True)

    # ── WhatsApp onboarding state (admin_whatsapp.py) ──────────────────────────
    # These three are referenced throughout admin_whatsapp.py (both the admin
    # add-number/request-otp/verify-otp/activate/save pipeline and the
    # merchant-facing submit-number/request-otp/submit-otp self-serve
    # endpoints) via cl.onboarding_status = .... They WERE already added to
    # the database by migration 0016_onboarding_columns — this model file was
    # just never updated to declare them, which is why every read needed
    # getattr(cl, "...", default) and every write would have raised
    # AttributeError despite the column existing on the actual table.
    # Width here (String(30)) matches 0016 exactly — do not shrink without a
    # new migration, even though the longest current value
    # ("number_submitted", 16 chars) would technically fit in less.
    #
    # Allowed values for onboarding_status (mirrors STATUS_* constants in
    # admin_whatsapp.py / admin.py):
    #   pending | number_submitted | added_to_waba | otp_requested |
    #   otp_submitted | otp_failed | number_in_use | number_personal |
    #   number_invalid | active
    onboarding_status = Column(
        String(30),
        nullable=False,
        server_default="pending",
        index=True,
        comment="WhatsApp onboarding state — see STATUS_* constants in admin_whatsapp.py",
    )

    # How many times the merchant has submitted/changed their WhatsApp number
    # via the self-serve flow. Capped at _MAX_NUMBER_ATTEMPTS in admin_whatsapp.py.
    number_submission_attempts = Column(
        Integer,
        nullable=False,
        server_default="0",
    )

    # The OTP code the merchant most recently entered, staged here so the
    # admin's /verify-otp step can pick it up and forward it to Meta. Cleared
    # by _clear_pending_otp() after a verify attempt (success or failure).
    pending_otp_code = Column(
        String(6),
        nullable=True,
    )

    # ── Delivery settings ──────────────────────────────────────────────────────
    delivery_enabled = Column(
        Boolean,
        nullable=False,
        server_default="false",
        comment="Whether this store offers delivery to customers",
    )

    delivery_fee = Column(
        Numeric(10, 2),
        nullable=True,
        comment="Flat delivery fee in local currency (e.g. NGN). "
                "Null means delivery is not priced yet.",
    )

    # ── Virtual assistant persona ──────────────────────────────────────────────
    assistant_name = Column(
        String(80),
        nullable=True,
        comment="Custom persona name shown in greetings e.g. 'Amara' or 'Chef Tunde'",
    )

    assistant_personality = Column(
        String(30),
        nullable=True,
        comment=(
            "Personality style injected into the AI system prompt. "
            "Accepted values: friendly_casual | professional | warm_enthusiastic"
        ),
    )

    # ── Store-managed settings permission ─────────────────────────────────────
    # When True the store dashboard is allowed to edit delivery/persona settings.
    # Merchant controls this; default off so new stores start locked.
    client_changes_enabled = Column(
        Boolean,
        nullable=False,
        server_default="false",
    )

    # ── Store hours ────────────────────────────────────────────────────────────
    opens_at = Column(String(5), nullable=True)
    closes_at = Column(String(5), nullable=True)

    store_timezone = Column(
        String(50),
        nullable=True,
        server_default=text("'Africa/Lagos'"),
    )

    # ── Foreign keys ───────────────────────────────────────────────────────────
    merchant_id = Column(
        String(length=20),
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # ── Relationships ──────────────────────────────────────────────────────────
    merchant = relationship(
        "Merchant",
        back_populates="clients",
        lazy="select",
    )

    whatsapp_credential = relationship(
        "ClientWhatsAppCredential",
        back_populates="client",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin",
        single_parent=True,
    )

    products = relationship(
        "Product",
        back_populates="client",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    orders = relationship(
        "Order",
        back_populates="client",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    carts = relationship(
        "Cart",
        back_populates="client",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    payments = relationship(
        "Payment",
        back_populates="client",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    inventories = relationship(
        "Inventory",
        back_populates="client",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    human_agent_tasks = relationship(
        "HumanAgent",
        back_populates="client",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    # ── Hotel domain (HoBS) ────────────────────────────────────────────────────
    room_types = relationship(
        "RoomType",
        back_populates="client",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    rooms = relationship(
        "Room",
        back_populates="client",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    room_bookings = relationship(
        "RoomBooking",
        back_populates="client",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    hotel_staff = relationship(
        "HotelStaff",
        back_populates="client",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    staff_action_logs = relationship(
        "StaffActionLog",
        cascade="all, delete-orphan",
        lazy="select",
    )

    permission_change_requests = relationship(
        "PermissionChangeRequest",
        cascade="all, delete-orphan",
        lazy="select",
    )

    flutterwave_subaccount = relationship(
        "FlutterwaveSubaccount",
        back_populates="client",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    # ── Helper properties ──────────────────────────────────────────────────────
    @property
    def has_whatsapp_credential(self) -> bool:
        return self.whatsapp_credential is not None

    @property
    def whatsapp_active(self):
        if self.whatsapp_credential is None:
            return None
        return bool(self.whatsapp_credential.active)

    @property
    def active_whatsapp_credential(self):
        if self.whatsapp_credential and self.whatsapp_credential.active:
            return self.whatsapp_credential
        return None

    @property
    def meta_phone_number_id(self):
        return (
            self.whatsapp_credential.phone_number_id
            if self.whatsapp_credential
            else None
        )

    @property
    def is_whatsapp_verified(self) -> bool:
        return bool(
            self.whatsapp_credential
            and self.whatsapp_credential.verified
        )

    @property
    def delivery_ready(self) -> bool:
        """True only when delivery is both enabled AND a fee has been configured."""
        return bool(self.delivery_enabled and self.delivery_fee is not None)

    @property
    def persona_name(self) -> str:
        """Returns the assistant name, falling back to the store name."""
        return self.assistant_name or f"{self.name} Assistant"

    @property
    def persona_style(self) -> str:
        """Returns personality style, defaulting to friendly_casual."""
        if self.assistant_personality in PERSONALITY_CHOICES:
            return self.assistant_personality
        return "friendly_casual"

    @property
    def has_login(self) -> bool:
        """True if the store has a dashboard password set."""
        return self.password_hash is not None

    def __repr__(self):
        return (
            f"<Client(id={self.id}, "
            f"name={self.name}, "
            f"delivery_enabled={self.delivery_enabled}, "
            f"merchant_id={self.merchant_id})>"
        )
