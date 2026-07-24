# app/models/cart.py
from sqlalchemy import (
    Column, String, Integer, Float, ForeignKey, Boolean, 
    DateTime, select, func, UniqueConstraint, Index
)
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy.orm import relationship, selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone
import uuid

from app.db.base import Base


class Cart(Base):
    __tablename__ = "carts"

    __table_args__ = (
        # uq_active_cart_per_user removed — it incorrectly blocked users
        # from having more than one completed order (checked_out=True).
        # The active-cart constraint is enforced in application logic via
        # get_active_cart() which filters on checked_out=False.
        Index("ix_carts_merchant_client_user", "merchant_id", "client_id", "user_id"),
        Index("ix_carts_checked_out", "checked_out"),
        Index("ix_carts_user_created", "user_id", "created_at"),
        {"comment": "Shopping carts for customers"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

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

    user_id = Column(String, nullable=False, index=True)

    created_at = Column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc), 
        nullable=False
    )
    
    checked_out = Column(Boolean, default=False, nullable=False)
    checked_out_at = Column(DateTime(timezone=True), nullable=True)


    # Relationships - NO BACKREF HERE
    items = relationship(
        "CartItem",
        back_populates="cart",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="CartItem.created_at",
    )

    client = relationship("Client", back_populates="carts", lazy="select")
    merchant = relationship("Merchant", back_populates="carts", lazy="select")
    
    # One-to-one with Order - NO BACKREF, using back_populates
    order = relationship(
        "Order", 
        back_populates="cart",  # ← CRITICAL: must match Order.cart back_populates
        uselist=False,
        cascade="save-update"
    )

    @property
    def calculated_total(self) -> float:
        if not self.items:
            return 0.0
        return sum(item.price_at_add * item.quantity for item in self.items)

    @staticmethod
    async def get_cart_by_id(db: AsyncSession, cart_id: str, for_update: bool = False):
        from sqlalchemy import select
        
        query = (
            select(Cart)
            .where(Cart.id == cart_id)
            .options(selectinload(Cart.items))
        )
        
        if for_update:
            query = query.with_for_update()
            
        result = await db.execute(query)
        return result.scalars().first()

    @staticmethod
    async def get_active_cart(
        db: AsyncSession, 
        merchant_id: str, 
        client_id: str, 
        user_id: str,
        for_update: bool = False
    ):
        from sqlalchemy import select
        
        query = (
            select(Cart)
            .where(
                Cart.merchant_id == merchant_id,
                Cart.client_id == client_id,
                Cart.user_id == user_id,
                Cart.checked_out == False
            )
            .options(selectinload(Cart.items))
            .order_by(Cart.created_at.desc())
            .limit(1)
        )
        
        if for_update:
            query = query.with_for_update()
            
        result = await db.execute(query)
        return result.scalars().first()

    def __repr__(self):
        return f"<Cart id={self.id} user={self.user_id} items={len(self.items)} checked_out={self.checked_out}>"


class CartItem(Base):
    __tablename__ = "cart_items"

    __table_args__ = (
        UniqueConstraint("cart_id", "product_id", name="uq_cart_product"),
        Index("ix_cart_items_product", "product_id"),
        Index("ix_cart_items_cart_created", "cart_id", "created_at"),
        {"comment": "Items in shopping carts"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    cart_id = Column(
        UUID(as_uuid=True),
        ForeignKey("carts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    product_id = Column(
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    quantity = Column(Integer, nullable=False)
    price_at_add = Column(Float, nullable=False)
    
    created_at = Column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc), 
        nullable=False
    )
    
    # Fixed metadata column

    # Relationships
    cart = relationship("Cart", back_populates="items", lazy="selectin")
    product = relationship("Product", back_populates="cart_items", lazy="select")

    @property
    def subtotal(self) -> float:
        return self.price_at_add * self.quantity

    def __repr__(self):
        return f"<CartItem cart={self.cart_id} product={self.product_id} qty={self.quantity}>"