# app/models/product.py
from sqlalchemy import Column, String, Text, Float, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid
from app.db.base import Base
import logging

logger = logging.getLogger(__name__)


class Product(Base):
    """
    Product definition under a tenant (merchant/client scope).
    Automatically tied to an Inventory record upon creation.

    New fields (migration 0007):
      image_url     — Cloudinary (or any public) URL for the product image.
                      Sent to the customer via WhatsApp image message when
                      they enquire about or add the product.
      variant_group — Groups products that are variations of the same base item
                      (e.g. all noodle types share variant_group='noodles').
                      When a customer asks for the group name, the bot lists
                      all variants and asks which one they want.
    """
    __tablename__ = "products"

    __table_args__ = (
        # Fast lookup when resolving variant groups for a store
        Index("ix_products_variant_group", "client_id", "variant_group"),
        # Fast category browsing
        Index("ix_products_category", "client_id", "category"),
    )

    # ── Primary key ────────────────────────────────────────────────────────────
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # ── Core fields ────────────────────────────────────────────────────────────
    name        = Column(String(255), nullable=False)
    description = Column(Text,        nullable=True)
    category    = Column(String(100), nullable=True)
    price       = Column(Float,       nullable=True)

    # ── Media ──────────────────────────────────────────────────────────────────
    image_url = Column(
        String(500),
        nullable=True,
        comment=(
            "Publicly accessible product image URL. "
            "Cloudinary free tier recommended. "
            "Must be a direct image link (not Google Drive / WhatsApp forward). "
            "Sent as a WhatsApp image message when the customer asks about this product."
        ),
    )

    # ── Variant grouping ───────────────────────────────────────────────────────
    variant_group = Column(
        String(100),
        nullable=True,
        comment=(
            "Lowercase group name shared by product variants. "
            "Examples: 'noodles', 'water', 'zobo'. "
            "When a customer asks for this group name, all matching products "
            "are listed and the customer is asked to choose. "
            "Leave null for standalone products."
        ),
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

    # ── Relationships ──────────────────────────────────────────────────────────
    merchant = relationship("Merchant", back_populates="products")
    client   = relationship("Client",   back_populates="products")

    inventory = relationship(
        "Inventory",
        back_populates="product",
        uselist=False,
        cascade="all, delete-orphan",
    )

    cart_items = relationship(
        "CartItem",
        back_populates="product",
        cascade="all, delete-orphan",
    )

    # ── Helper properties ──────────────────────────────────────────────────────
    @property
    def has_image(self) -> bool:
        return bool(self.image_url)

    @property
    def is_variant(self) -> bool:
        """True when this product belongs to a variant group."""
        return bool(self.variant_group)

    @property
    def display_price(self) -> str:
        """Human-readable price string for bot responses."""
        import os
        symbol = os.getenv("CURRENCY_SYMBOL", "₦")
        if self.price is None:
            return "Price on request"
        return f"{symbol}{self.price:,.0f}"

    @property
    def in_stock(self) -> bool:
        """Convenience — True if inventory exists and quantity > 0."""
        if self.inventory is None:
            return False
        return self.inventory.quantity > 0

    def __repr__(self):
        return (
            f"<Product(id={self.id}, name={self.name!r}, "
            f"variant_group={self.variant_group!r}, "
            f"price={self.price})>"
        )
