# app/models/room.py
from sqlalchemy import Column, String, ForeignKey, Boolean, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid
from app.db.base import Base
import logging

logger = logging.getLogger(__name__)


class Room(Base):
    """
    A single, individually numbered physical room. This has no direct
    equivalent in ShoprHQ — Product/Inventory tracked a stock *count*
    ("12 units of noodles left"), but a hotel room isn't fungible stock,
    it's a specific numbered unit that is either free or booked for a
    specific date range.

    Availability is NOT a boolean column on this table (a room can be
    free today and booked next week). It is derived by querying
    RoomBooking for overlapping date ranges against this room_id — see
    RoomBooking.is_room_available_for_range(). `is_active` here only
    means "this room currently exists / is listed", e.g. for temporarily
    taking a room out of service for maintenance.
    """
    __tablename__ = "rooms"

    __table_args__ = (
        UniqueConstraint("client_id", "room_number", name="uq_room_number_per_hotel"),
        Index("ix_rooms_client", "client_id"),
        Index("ix_rooms_room_type", "room_type_id"),
    )

    # ── Primary key ────────────────────────────────────────────────────────────
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # ── Core fields ────────────────────────────────────────────────────────────
    room_number = Column(
        String(20),
        nullable=False,
        comment="As written on the door / used by staff, e.g. '4', '12B', 'Suite 3'.",
    )

    is_active = Column(
        Boolean,
        default=True,
        nullable=False,
        comment="False = temporarily out of service (maintenance, renovation). Excluded from availability.",
    )

    # ── Foreign keys ───────────────────────────────────────────────────────────
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
    room_type_id = Column(
        UUID(as_uuid=True),
        ForeignKey("room_types.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="RESTRICT, not CASCADE — don't allow deleting a room type that still has rooms under it.",
    )

    # ── Relationships ──────────────────────────────────────────────────────────
    merchant  = relationship("Merchant",  back_populates="rooms")
    client    = relationship("Client",    back_populates="rooms")
    room_type = relationship("RoomType",  back_populates="rooms")

    bookings = relationship(
        "RoomBooking",
        back_populates="room",
        cascade="all, delete-orphan",
        lazy="select",
    )

    def __repr__(self):
        return f"<Room(id={self.id}, room_number={self.room_number!r}, room_type_id={self.room_type_id})>"
