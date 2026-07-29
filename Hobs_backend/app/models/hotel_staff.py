# app/models/hotel_staff.py
from sqlalchemy import Column, String, DateTime, ForeignKey, Boolean, func, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid
from app.db.base import Base
import logging

logger = logging.getLogger(__name__)

# Role hierarchy, low to high. Higher roles inherit everything lower roles
# can do. "front_desk"/"admin" (the original Phase-2 values) are kept as
# accepted aliases below so any already-seeded rows don't break, but new
# rows should use these three.
ROLE_RECEPTIONIST = "receptionist"
ROLE_MANAGER = "manager"
ROLE_TOP_MANAGER = "top_manager"

_ROLE_RANK = {
    "front_desk": 0,       # legacy alias for receptionist
    ROLE_RECEPTIONIST: 0,
    ROLE_MANAGER: 1,
    "admin": 2,             # legacy alias for top_manager
    ROLE_TOP_MANAGER: 2,
}


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

    Permission model (see docs/PERMISSIONS.md):
      - receptionist: WhatsApp booking updates only (book/check-in/check-out).
        Cannot cancel a paid booking, cannot touch pricing, no dashboard access.
      - manager: everything receptionist can, plus price edits, full admin
        drill-down, gets notified on high-impact actions, can review/revert.
      - top_manager: everything manager can, plus assigns staff roles from
        the dashboard -- and ONLY from the dashboard, gated by a one-time
        email code (see PermissionChangeRequest). Role changes are never
        possible via WhatsApp, by design, so a compromised WhatsApp session
        can never escalate anyone's access.

    email is nullable for receptionist (WhatsApp-only staff never need it)
    but required in practice for manager/top_manager, since the
    permission-change code flow has nowhere to send the code otherwise --
    enforced at the service layer, not a DB constraint, since a manager
    could exist briefly without dashboard access configured yet.
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

    email = Column(
        String(255), nullable=True,
        comment="Required in practice for manager/top_manager -- destination for permission-change confirmation codes.",
    )

    role = Column(
        String(20), nullable=False, default=ROLE_RECEPTIONIST,
        comment="receptionist | manager | top_manager. Legacy values front_desk/admin still accepted as aliases.",
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

    # ── Permission helpers ─────────────────────────────────────────────────────
    @property
    def rank(self) -> int:
        return _ROLE_RANK.get(self.role, 0)

    def is_at_least(self, role: str) -> bool:
        """e.g. staff.is_at_least(ROLE_MANAGER) -> True for manager and top_manager."""
        return self.rank >= _ROLE_RANK.get(role, 0)

    def can_cancel_paid_booking(self) -> bool:
        return self.is_at_least(ROLE_MANAGER)

    def can_edit_prices(self) -> bool:
        return self.is_at_least(ROLE_MANAGER)

    def can_review_flagged_actions(self) -> bool:
        return self.is_at_least(ROLE_MANAGER)

    def can_assign_roles(self) -> bool:
        return self.is_at_least(ROLE_TOP_MANAGER)

    def __repr__(self):
        return f"<HotelStaff(id={self.id}, phone={self.phone_number!r}, role={self.role!r})>"
