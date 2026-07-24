# app/models/room_type.py
from sqlalchemy import Column, String, Text, Float, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid
from app.db.base import Base
import logging

logger = logging.getLogger(__name__)


class RoomType(Base):
    """
    A category of room offered by a hotel (client), e.g. "Standard", "Deluxe",
    "Executive Suite". Ported from Product: same flat, admin-adjustable price
    model — hotel staff/owners edit this the same way store owners edit
    product prices, via the dashboard or the CRUD endpoints in
    app/api/v1/room_type.py (mirrors app/api/v1/product.py).

    Each RoomType can have many individual Room units (see room.py). Price
    lives on RoomType, not on Room, so raising the price of "Deluxe" updates
    every deluxe room at once without touching each room row.
    """
    __tablename__ = "room_types"

    __table_args__ = (
        Index("ix_room_types_client", "client_id"),
    )

    # ── Primary key ────────────────────────────────────────────────────────────
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # ── Core fields ────────────────────────────────────────────────────────────
    name        = Column(String(255), nullable=False)   # "Deluxe Room"
    description = Column(Text,        nullable=True)     # amenities, bed size, etc.
    price       = Column(Float,       nullable=False)    # flat nightly rate, admin-editable

    image_url = Column(
        String(500),
        nullable=True,
        comment="Publicly accessible room photo URL, sent to guests on WhatsApp when they ask about this room type.",
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
        comment="The hotel this room type belongs to (Client == Hotel in this deployment).",
    )

    # ── Relationships ──────────────────────────────────────────────────────────
    merchant = relationship("Merchant", back_populates="room_types")
    client   = relationship("Client",   back_populates="room_types")

    rooms = relationship(
        "Room",
        back_populates="room_type",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    # ── Helper properties ──────────────────────────────────────────────────────
    @property
    def display_price(self) -> str:
        import os
        symbol = os.getenv("CURRENCY_SYMBOL", "₦")
        return f"{symbol}{self.price:,.0f} / night"

    def __repr__(self):
        return f"<RoomType(id={self.id}, name={self.name!r}, price={self.price})>"
