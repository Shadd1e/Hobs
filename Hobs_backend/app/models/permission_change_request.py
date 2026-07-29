# app/models/permission_change_request.py
import secrets
import string
from datetime import datetime, timezone, timedelta

from sqlalchemy import Column, String, DateTime, ForeignKey, Integer, func, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid
from app.db.base import Base


def generate_permission_code(length: int = 6) -> str:
    return "".join(secrets.choice(string.digits) for _ in range(length))


class PermissionChangeRequest(Base):
    """
    The ONLY path by which a staff member's role can change. Deliberately
    has no WhatsApp-triggerable equivalent anywhere in the codebase --
    initiated from the dashboard by a top_manager, confirmed by a code
    emailed to that SAME top_manager's registered email, and applied only
    on successful confirmation. This is the guard against a compromised
    WhatsApp session (lost phone, SIM swap, staff turnover without
    deactivation) ever being able to escalate anyone's access.

    code is a short-lived (10 min), single-use, 6-digit code mailed to a
    verified address -- same risk class as a typical email OTP, plaintext
    storage here is an accepted tradeoff given the short expiry and single
    use, not something reused as a long-lived credential.
    """
    __tablename__ = "permission_change_requests"

    __table_args__ = (
        Index("ix_permission_requests_pending", "client_id", "confirmed_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    merchant_id = Column(String(20), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True)
    client_id   = Column(String(20), ForeignKey("clients.id",   ondelete="CASCADE"), nullable=False, index=True)

    requested_by_staff_id = Column(UUID(as_uuid=True), ForeignKey("hotel_staff.id", ondelete="CASCADE"), nullable=False)
    target_staff_id = Column(UUID(as_uuid=True), ForeignKey("hotel_staff.id", ondelete="CASCADE"), nullable=False)

    old_role = Column(String(20), nullable=False)
    new_role = Column(String(20), nullable=False)

    code = Column(String(6), nullable=False, default=generate_permission_code)
    email_sent_to = Column(String(255), nullable=False)

    expires_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    confirmed_at = Column(DateTime(timezone=True), nullable=True)
    attempts = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # ── Relationships ──────────────────────────────────────────────────────────
    requested_by = relationship("HotelStaff", foreign_keys=[requested_by_staff_id])
    target_staff = relationship("HotelStaff", foreign_keys=[target_staff_id])

    @property
    def is_expired(self) -> bool:
        now = datetime.now(timezone.utc)
        expires = self.expires_at if self.expires_at.tzinfo else self.expires_at.replace(tzinfo=timezone.utc)
        return now > expires

    @property
    def is_pending(self) -> bool:
        return self.confirmed_at is None and not self.is_expired

    def __repr__(self):
        return f"<PermissionChangeRequest(id={self.id}, target={self.target_staff_id}, new_role={self.new_role!r})>"
