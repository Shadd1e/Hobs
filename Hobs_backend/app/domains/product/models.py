from sqlalchemy import Column, String, Text, Float, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid
import logging

from app.infrastructure.db.base  import Base

logger = logging.getLogger(__name__)


class Product(Base):
    """
    Product definition under a tenant (merchant/client scope).
    Automatically tied to an inventory record upon creation.
    """
    __tablename__ = "products"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    name = Column(String(255), nullable=False)

    description = Column(Text, nullable=True)

    merchant_id = Column(
        String(6),
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    client_id = Column(
        String(6),
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    category = Column(String(100), nullable=True)

    price = Column(Float, nullable=True)

    merchant = relationship("Merchant", back_populates="products")

    client = relationship("Client", back_populates="products")

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