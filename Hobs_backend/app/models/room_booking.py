# app/models/room_booking.py
from sqlalchemy import (
    Column, String, DateTime, Date, ForeignKey, func, Enum,
    Numeric, Index, Text, select, and_, or_
)
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import relationship
from app.db.base import Base
import uuid
import enum
import secrets
import string
from datetime import datetime, timezone, date


def generate_booking_code(length: int = 8) -> str:
    alphabet = string.ascii_uppercase + string.digits
    safe_alphabet = ''.join(c for c in alphabet if c not in '0O1Il')
    return "".join(secrets.choice(safe_alphabet) for _ in range(length))


class BookingSource(str, enum.Enum):
    GUEST_WHATSAPP = "guest_whatsapp"   # guest booked + paid themselves via the bot
    STAFF_WHATSAPP = "staff_whatsapp"   # staff logged a walk-in / phone booking by text
    DASHBOARD      = "dashboard"        # entered manually from the admin dashboard


class BookingStatus(str, enum.Enum):
    CREATED         = "CREATED"          # booking intent captured, no payment yet
    PENDING_PAYMENT = "PENDING_PAYMENT"  # Paystack link generated, awaiting webhook
    PAID            = "PAID"             # payment confirmed — room is now locked for these dates
    CHECKED_IN      = "CHECKED_IN"
    CHECKED_OUT     = "CHECKED_OUT"
    CANCELLED       = "CANCELLED"
    REFUNDED        = "REFUNDED"

    @classmethod
    def can_transition_to(cls, from_status: "BookingStatus", to_status: "BookingStatus") -> bool:
        valid_transitions = {
            cls.CREATED: {cls.PENDING_PAYMENT, cls.PAID, cls.CANCELLED},
            cls.PENDING_PAYMENT: {cls.PAID, cls.CANCELLED},
            cls.PAID: {cls.CHECKED_IN, cls.CANCELLED, cls.REFUNDED},
            cls.CHECKED_IN: {cls.CHECKED_OUT},
            cls.CHECKED_OUT: {cls.REFUNDED},
            cls.CANCELLED: set(),
            cls.REFUNDED: set(),
        }
        return to_status in valid_transitions.get(from_status, set())

    @property
    def is_terminal(self) -> bool:
        return self in (BookingStatus.CHECKED_OUT, BookingStatus.CANCELLED, BookingStatus.REFUNDED)

    @property
    def holds_the_room(self) -> bool:
        """
        Per the product decision: a room is only locked from other bookings
        once payment is CONFIRMED, not merely initiated. So PENDING_PAYMENT
        does NOT hold the room — only PAID and CHECKED_IN do.
        (Known tradeoff: two guests can be mid-payment on the same room at
        once. Flagged for a future soft-hold on PENDING_PAYMENT if double
        bookings become a real problem.)
        """
        return self in (BookingStatus.PAID, BookingStatus.CHECKED_IN)


class RoomBooking(Base):
    """
    A stay: one room, one date range, one guest. Ported from Order, with
    cart_id/delivery fields replaced by room_id/check_in/check_out.

    Can be created two ways:
      - Guest books + pays via WhatsApp bot -> source=GUEST_WHATSAPP,
        starts CREATED, moves to PENDING_PAYMENT -> PAID via Paystack webhook.
      - Staff texts a booking in directly (walk-in guest, phone booking,
        or backfilling a paper booking) -> source=STAFF_WHATSAPP,
        created straight into PAID (no payment collected through us) or
        PENDING_PAYMENT if staff say payment is still owed.
    """
    __tablename__ = "room_bookings"

    __table_args__ = (
        Index("ix_bookings_merchant_client", "merchant_id", "client_id"),
        Index("ix_bookings_room_dates", "room_id", "check_in", "check_out"),
        Index("ix_bookings_status", "status"),
        Index("ix_bookings_created_at", "created_at"),
        Index("ix_bookings_code_lookup", "booking_code", "merchant_id"),
        {"comment": "Guest room bookings/stays"},
    )

    # ── Primary key ────────────────────────────────────────────────────────────
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    booking_code = Column(
        String(8), unique=True, nullable=False,
        default=generate_booking_code, index=True,
    )

    # ── Foreign keys ───────────────────────────────────────────────────────────
    merchant_id = Column(String(20), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True)
    client_id   = Column(String(20), ForeignKey("clients.id",   ondelete="CASCADE"), nullable=False, index=True)
    room_id     = Column(UUID(as_uuid=True), ForeignKey("rooms.id", ondelete="RESTRICT"), nullable=False, index=True)

    # ── Guest info ─────────────────────────────────────────────────────────────
    guest_name        = Column(String(100), nullable=True)
    guest_phone        = Column(String(20),  nullable=True, index=True, comment="WhatsApp number of the guest, if booked via bot.")

    # ── Stay dates ─────────────────────────────────────────────────────────────
    check_in  = Column(Date, nullable=False)
    check_out = Column(Date, nullable=False)

    # ── Money ──────────────────────────────────────────────────────────────────
    total_amount = Column(Numeric(12, 2), nullable=False, comment="room_type.price * nights, snapshotted at booking time")
    amount_paid  = Column(Numeric(12, 2), nullable=True)
    payment_ref  = Column(String(100), nullable=True, index=True, comment="Paystack transaction reference")

    status = Column(
        Enum(BookingStatus, name="booking_status", create_constraint=True),
        nullable=False, default=BookingStatus.CREATED, index=True,
    )
    source = Column(
        Enum(BookingSource, name="booking_source", create_constraint=True),
        nullable=False, default=BookingSource.GUEST_WHATSAPP,
    )

    # Who logged it, when staff typed it in via WhatsApp (for the admin
    # drill-down: "logged by" field the dashboard shows on a booked room).
    logged_by_staff_phone = Column(String(20), nullable=True)

    # Free-text as staff actually typed it, kept for audit/debugging the
    # fuzzy-match extraction — e.g. "rum 4 boked 3 nyt".
    raw_staff_message = Column(Text, nullable=True)

    reminder_sent_at = Column(
        DateTime(timezone=True), nullable=True,
        comment="Set once the pre-checkout reminder has fired, so the reminder job doesn't resend it.",
    )

    booking_metadata = Column("metadata", JSON, nullable=True)

    created_at    = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    confirmed_at  = Column(DateTime(timezone=True), nullable=True)
    checked_in_at = Column(DateTime(timezone=True), nullable=True)
    checked_out_at = Column(DateTime(timezone=True), nullable=True)
    cancelled_at  = Column(DateTime(timezone=True), nullable=True)
    updated_at    = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # ── Relationships ──────────────────────────────────────────────────────────
    merchant = relationship("Merchant", back_populates="room_bookings")
    client   = relationship("Client",   back_populates="room_bookings")
    room     = relationship("Room",     back_populates="bookings")

    # ── Repr ───────────────────────────────────────────────────────────────────
    def __repr__(self):
        return f"<RoomBooking {self.booking_code} room={self.room_id} ({self.status.value})>"

    # ── Computed properties ────────────────────────────────────────────────────
    @property
    def nights(self) -> int:
        return (self.check_out - self.check_in).days

    @property
    def is_active_hold(self) -> bool:
        return self.status.holds_the_room

    # ── Status transition ──────────────────────────────────────────────────────
    async def transition_to(self, new_status: BookingStatus, db_session: AsyncSession) -> bool:
        if not BookingStatus.can_transition_to(self.status, new_status):
            raise ValueError(f"Cannot transition booking from {self.status.value} to {new_status.value}")

        self.status = new_status
        now = datetime.now(timezone.utc)
        if new_status == BookingStatus.PAID and not self.confirmed_at:
            self.confirmed_at = now
        elif new_status == BookingStatus.CHECKED_IN:
            self.checked_in_at = now
        elif new_status == BookingStatus.CHECKED_OUT:
            self.checked_out_at = now
        elif new_status == BookingStatus.CANCELLED:
            self.cancelled_at = now

        self.updated_at = now
        db_session.add(self)
        return True

    # ── Availability — the core query the whole system depends on ─────────────
    @classmethod
    async def is_room_available(
        cls,
        db_session: AsyncSession,
        room_id,
        check_in: date,
        check_out: date,
        exclude_booking_id: str = None,
    ) -> bool:
        """
        True if `room_id` has no PAID/CHECKED_IN booking overlapping
        [check_in, check_out). Standard half-open interval overlap check:
        two ranges overlap iff existing.check_in < new.check_out AND
        existing.check_out > new.check_in.

        Only bookings where status.holds_the_room is True block availability
        — per the product decision, PENDING_PAYMENT does not hold the room.
        """
        query = select(cls.id).where(
            cls.room_id == room_id,
            cls.status.in_([BookingStatus.PAID, BookingStatus.CHECKED_IN]),
            cls.check_in < check_out,
            cls.check_out > check_in,
        )
        if exclude_booking_id:
            query = query.where(cls.id != exclude_booking_id)

        result = await db_session.execute(query)
        return result.scalar_one_or_none() is None

    @classmethod
    async def get_by_booking_code(
        cls, db_session: AsyncSession, booking_code: str,
        merchant_id: str = None, client_id: str = None, for_update: bool = False,
    ):
        query = select(cls).where(cls.booking_code == booking_code)
        if merchant_id:
            query = query.where(cls.merchant_id == merchant_id)
        if client_id:
            query = query.where(cls.client_id == client_id)
        if for_update:
            query = query.with_for_update()
        result = await db_session.execute(query)
        return result.scalar_one_or_none()

    @classmethod
    async def get_active_booking_for_room(
        cls, db_session: AsyncSession, room_id, for_update: bool = False,
    ):
        """The current PAID/CHECKED_IN booking occupying this room right now, if any — powers the dashboard drill-down."""
        today = datetime.now(timezone.utc).date()
        query = (
            select(cls)
            .where(
                cls.room_id == room_id,
                cls.status.in_([BookingStatus.PAID, BookingStatus.CHECKED_IN]),
                cls.check_in <= today,
                cls.check_out > today,
            )
            .order_by(cls.check_in.desc())
            .limit(1)
        )
        if for_update:
            query = query.with_for_update()
        result = await db_session.execute(query)
        return result.scalar_one_or_none()

    @classmethod
    async def get_bookings_needing_checkout_reminder(cls, db_session: AsyncSession, hours_before: int = 3):
        """Used by the checkout reminder worker job."""
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) + timedelta(hours=hours_before)).date()
        query = select(cls).where(
            cls.status == BookingStatus.CHECKED_IN,
            cls.check_out <= cutoff,
            cls.reminder_sent_at.is_(None),
        )
        result = await db_session.execute(query)
        return result.scalars().all()
