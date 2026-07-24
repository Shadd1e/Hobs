# app/models/inventory.py

import logging
logger = logging.getLogger(__name__)

from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    ForeignKey,
    UniqueConstraint,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid

from app.db.base import Base


class Inventory(Base):
    """
    Mirrors available stock for a product under a specific tenant.

    RULES:
    - quantity is the single source of truth
    - inventory is modified ONLY during checkout
    - inventory is tenant-scoped (merchant + client + product)
    """

    __tablename__ = "inventories"

    __table_args__ = (
        UniqueConstraint(
            "product_id",
            "merchant_id",
            "client_id",
            name="uq_inventory_per_tenant_product",
        ),
        Index("ix_inventory_tenant_product", "merchant_id", "client_id", "product_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    product_id = Column(
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

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

    # Single inventory state
    quantity = Column(Integer, nullable=False, default=0)

    # Low stock warning threshold — notify operator when quantity drops to or below this
    # NULL means no threshold set (no warnings)
    low_stock_threshold = Column(Integer, nullable=True)

    # Optional metadata
    unit_price = Column(Float, nullable=True)
    warehouse_location = Column(String(255), nullable=True)

    # Relationships
    product = relationship("Product", back_populates="inventory")
    merchant = relationship("Merchant", back_populates="inventories")
    client = relationship("Client", back_populates="inventories")