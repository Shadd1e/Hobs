# app/models/staff_action_log.py
from sqlalchemy import Column, String, DateTime, ForeignKey, Boolean, Text, func, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid
from app.db.base import Base


class StaffActionLog(Base):
    """
    Append-only audit trail for every staff-driven room/booking change.
    DELIBERATELY has no update-in-place semantics anywhere in the codebase
    -- a revert creates a NEW row pointing back at the original via
    reverted_by_log_id, it never edits or deletes the original row. This
    is the "tamper-evident" property: if a hotel owner ever needs to prove
    what happened (staff dispute, insurance claim, tax audit), this table
    has to hold up as a genuine record, not something anyone could quietly
    edit after the fact.

    Every staff WhatsApp action that mutates a booking writes one of
    these, not just the "high impact" ones -- is_high_impact just controls
    whether it triggers a manager notification, not whether it's logged.
    """
    __tablename__ = "staff_action_logs"

    __table_args__ = (
        Index("ix_action_logs_hotel_created", "client_id", "created_at"),
        Index("ix_action_logs_staff", "staff_id"),
        Index("ix_action_logs_review_pending", "client_id", "reviewed"),
        {"comment": "Append-only. Never UPDATE previous_status/new_status/action on an existing row."},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    merchant_id = Column(String(20), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True)
    client_id   = Column(String(20), ForeignKey("clients.id",   ondelete="CASCADE"), nullable=False, index=True)

    staff_id = Column(UUID(as_uuid=True), ForeignKey("hotel_staff.id", ondelete="SET NULL"), nullable=True)
    staff_phone_snapshot = Column(
        String(20), nullable=False,
        comment="Phone number at time of action, kept even if the HotelStaff row is later deleted.",
    )

    room_id = Column(UUID(as_uuid=True), ForeignKey("rooms.id", ondelete="SET NULL"), nullable=True)
    booking_id = Column(String(36), ForeignKey("room_bookings.id", ondelete="SET NULL"), nullable=True)

    action = Column(
        String(30), nullable=False,
        comment="book | check_in | check_out | cancel | price_change | revert",
    )
    previous_status = Column(String(30), nullable=True)
    new_status = Column(String(30), nullable=True)

    raw_message = Column(Text, nullable=True, comment="What the staff member actually typed, for audit context.")

    is_high_impact = Column(
        Boolean, nullable=False, default=False,
        comment="Cancelling a paid/checked-in booking, or similar revenue-affecting actions -- triggers manager notification.",
    )

    reviewed = Column(Boolean, nullable=False, default=False)
    reviewed_by_staff_id = Column(UUID(as_uuid=True), ForeignKey("hotel_staff.id", ondelete="SET NULL"), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)

    reverted = Column(Boolean, nullable=False, default=False)
    # Points at the NEW log row created by the revert action -- the original
    # row is never mutated, this just links forward to what undid it.
    reverted_by_log_id = Column(UUID(as_uuid=True), ForeignKey("staff_action_logs.id", ondelete="SET NULL"), nullable=True)

    revert_code = Column(
        String(8), nullable=True, index=True,
        comment="Short code a manager can reply with on WhatsApp ('undo ABC123') to revert this specific action.",
    )
    revert_expires_at = Column(
        DateTime(timezone=True), nullable=True,
        comment="Revert window -- shown to the manager as a countdown, per the product decision to create urgency without full pre-approval friction.",
    )

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # ── Relationships ──────────────────────────────────────────────────────────
    staff = relationship("HotelStaff", foreign_keys=[staff_id])
    reviewed_by = relationship("HotelStaff", foreign_keys=[reviewed_by_staff_id])

    def __repr__(self):
        return f"<StaffActionLog(id={self.id}, action={self.action!r}, high_impact={self.is_high_impact})>"
