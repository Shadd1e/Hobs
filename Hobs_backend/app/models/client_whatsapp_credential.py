from sqlalchemy import Column, String, Boolean, ForeignKey, DateTime, func
from sqlalchemy.orm import relationship
from app.db.base import Base
import logging

logger = logging.getLogger(__name__)

# Valid status values — do not change without a migration
CREDENTIAL_STATUS_PENDING      = "pending"       # number submitted, nothing done yet
CREDENTIAL_STATUS_OTP_SENT     = "otp_sent"      # admin clicked Activate, OTP on its way
CREDENTIAL_STATUS_OTP_VERIFIED = "otp_verified"  # merchant entered correct OTP
CREDENTIAL_STATUS_ACTIVE       = "active"        # fully registered, webhook live, store live

CREDENTIAL_STATUSES = frozenset({
    CREDENTIAL_STATUS_PENDING,
    CREDENTIAL_STATUS_OTP_SENT,
    CREDENTIAL_STATUS_OTP_VERIFIED,
    CREDENTIAL_STATUS_ACTIVE,
})


class ClientWhatsAppCredential(Base):
    """
    ONE client → ONE WhatsApp phone_number_id.

    Status state machine:
        pending  →  otp_sent  →  otp_verified  →  active

    The `active` boolean is kept for fast filtering but is always
    derived from status: set active=True only when status='active'.
    Never set active directly — always go through the status field.
    """

    __tablename__ = "client_whatsapp_credentials"

    client_id = Column(
        String(length=20),
        ForeignKey("clients.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )

    # Meta-issued identifier for this phone number — required for all API calls
    phone_number_id = Column(String(255), nullable=False, unique=True, index=True)

    # E.164-ish display number e.g. "2348012345678" (no + stored)
    whatsapp_number = Column(String(20), nullable=True)

    # ── Onboarding state ───────────────────────────────────────────────
    # Source of truth for where this store is in the activation pipeline.
    # Allowed values: pending | otp_sent | otp_verified | active
    status = Column(
        String(20),
        nullable=False,
        default=CREDENTIAL_STATUS_PENDING,
        index=True,
        comment="Onboarding state: pending | otp_sent | otp_verified | active",
    )

    # Convenience flag — True only when status='active'.
    # Kept for backwards compat with existing code that checks .active.
    active = Column(Boolean, default=False, index=True)

    # Set True once Meta's /verify_code call succeeds (admin_whatsapp.py
    # verify_otp). Distinct from `active`, which additionally requires
    # /register + webhook subscription to have completed. Referenced by
    # Client.is_whatsapp_verified, which was reading this before it existed
    # as a column — added now to match.
    verified = Column(Boolean, default=False, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # ── Relationship ───────────────────────────────────────────────────
    client = relationship(
        "Client",
        back_populates="whatsapp_credential",
        uselist=False,
        lazy="selectin",
        single_parent=True,
    )

    # ── Helper properties ──────────────────────────────────────────────
    @property
    def merchant_id(self):
        return self.client.merchant_id if self.client else None

    @property
    def is_live(self) -> bool:
        """True only when the store is fully active and taking messages."""
        return self.status == CREDENTIAL_STATUS_ACTIVE

    @property
    def is_pending_otp(self) -> bool:
        """True when OTP has been sent and merchant needs to enter it."""
        return self.status == CREDENTIAL_STATUS_OTP_SENT

    def mark_otp_sent(self) -> None:
        """Call after admin triggers OTP request via Meta API."""
        self.status = CREDENTIAL_STATUS_OTP_SENT
        self.active = False

    def mark_otp_verified(self) -> None:
        """Call after merchant submits correct OTP."""
        self.status = CREDENTIAL_STATUS_OTP_VERIFIED
        self.active = False
        self.verified = True

    def mark_active(self) -> None:
        """
        Call after register + subscribe-webhook complete successfully.
        This is the final state — store is live.
        """
        self.status = CREDENTIAL_STATUS_ACTIVE
        self.active = True

    def __repr__(self):
        return (
            f"<ClientWhatsAppCredential("
            f"client_id={self.client_id}, "
            f"status={self.status}, "
            f"phone_number_id={self.phone_number_id})>"
        )
