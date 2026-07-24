import uuid
import enum
import secrets
import string

from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    DateTime,
    Boolean,
    ForeignKey,
    UniqueConstraint,
    Index,
    Numeric,
    Enum,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy.orm import relationship, selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.base import Base


def generate_order_code(length: int = 8) -> str:
    alphabet = string.ascii_uppercase + string.digits
    safe_alphabet = "".join(c for c in alphabet if c not in "0O1Il")
    return "".join(secrets.choice(safe_alphabet) for _ in range(length))


class OrderStatus(str, enum.Enum):
    CREATED          = "CREATED"
    PENDING_PAYMENT  = "PENDING_PAYMENT"
    PAID             = "PAID"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"   # delivery orders in transit
    AWAITING_PICKUP  = "AWAITING_PICKUP"
    FULFILLED        = "FULFILLED"
    CANCELLED        = "CANCELLED"
    REFUNDED         = "REFUNDED"

    @classmethod
    def can_transition_to(cls, from_status: "OrderStatus", to_status: "OrderStatus") -> bool:
        valid_transitions = {
            cls.CREATED: {cls.PENDING_PAYMENT, cls.PAID, cls.AWAITING_PICKUP, cls.CANCELLED},
            cls.PENDING_PAYMENT: {cls.PAID, cls.CANCELLED},
            cls.PAID: {
                cls.OUT_FOR_DELIVERY,   # delivery orders go in-transit
                cls.AWAITING_PICKUP,    # pickup orders go straight here
                cls.REFUNDED,
            },
            cls.OUT_FOR_DELIVERY: {cls.FULFILLED, cls.CANCELLED},
            cls.AWAITING_PICKUP: {cls.FULFILLED, cls.CANCELLED},
            cls.FULFILLED: {cls.REFUNDED},
            cls.CANCELLED: set(),
            cls.REFUNDED: set(),
        }
        return to_status in valid_transitions.get(from_status, set())


class Order(Base):
    __tablename__ = "orders"

    __table_args__ = (
        UniqueConstraint("cart_id", name="uq_order_per_cart"),
        Index("ix_orders_merchant_client", "merchant_id", "client_id"),
        Index("ix_orders_user_status", "user_id", "status"),
        Index("ix_orders_merchant_status", "merchant_id", "status"),
        Index("ix_orders_created_at", "created_at"),
        Index("ix_orders_order_code_lookup", "order_code", "merchant_id"),
        {"comment": "Orders placed by customers through checkout"},
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    order_code = Column(
        String(8),
        unique=True,
        nullable=False,
        default=generate_order_code,
        index=True,
    )

    cart_id = Column(
        UUID(as_uuid=True),
        ForeignKey("carts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        unique=True,
    )

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

    user_id = Column(String, nullable=False, index=True)

    customer_name = Column(String(100), nullable=True)

    payment_method = Column(String(20), nullable=False, index=True)

    total_amount = Column(Numeric(12, 2), nullable=False)

    status = Column(
        # name="orderstatus" must match the pg type created in 0001_initial.py
        Enum(OrderStatus, name="order_status", create_constraint=True),
        nullable=False,
        default=OrderStatus.CREATED,
        index=True,
    )

    order_metadata = Column("metadata", JSON, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    confirmed_at = Column(DateTime(timezone=True), nullable=True)

    fulfilled_at = Column(DateTime(timezone=True), nullable=True)

    cancelled_at = Column(DateTime(timezone=True), nullable=True)

    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    cart = relationship(
        "Cart",
        back_populates="order",
        lazy="select",
        uselist=False,
    )

    merchant = relationship("Merchant", back_populates="orders", lazy="select")

    client = relationship("Client", back_populates="orders", lazy="select")

    payments = relationship(
        "Payment",
        back_populates="order",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="Payment.created_at.desc()",
    )

    def __repr__(self):
        return f"<Order {self.order_code} ({self.status.value})>"

    @property
    def is_paid(self) -> bool:
        return self.status in (
            OrderStatus.PAID,
            OrderStatus.OUT_FOR_DELIVERY,
            OrderStatus.AWAITING_PICKUP,
            OrderStatus.FULFILLED,
        )

    @property
    def is_cancellable(self) -> bool:
        return self.status in (
            OrderStatus.CREATED,
            OrderStatus.PENDING_PAYMENT,
        )

    async def transition_to(self, new_status: OrderStatus, db_session) -> bool:
        if not OrderStatus.can_transition_to(self.status, new_status):
            raise ValueError(
                f"Cannot transition from {self.status.value} to {new_status.value}"
            )

        self.status = new_status

        now = datetime.now(timezone.utc)

        if new_status == OrderStatus.PAID and not self.confirmed_at:
            self.confirmed_at = now
        elif new_status == OrderStatus.OUT_FOR_DELIVERY:
            pass  # no dedicated timestamp yet; add dispatched_at if needed
        elif new_status == OrderStatus.FULFILLED:
            self.fulfilled_at = now
        elif new_status == OrderStatus.CANCELLED:
            self.cancelled_at = now

        self.updated_at = now
        db_session.add(self)

        return True

    @classmethod
    async def get_by_order_code(
        cls,
        db_session,
        order_code: str,
        merchant_id: str | None = None,
        client_id: str | None = None,
        for_update: bool = False,
    ):
        query = select(cls).where(cls.order_code == order_code)

        if merchant_id:
            query = query.where(cls.merchant_id == merchant_id)

        if client_id:
            query = query.where(cls.client_id == client_id)

        if for_update:
            query = query.with_for_update()

        result = await db_session.execute(query)

        return result.scalar_one_or_none()

    @classmethod
    async def get_recent_orders(
        cls,
        db_session,
        merchant_id: str,
        client_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ):
        query = select(cls).where(cls.merchant_id == merchant_id)

        if client_id:
            query = query.where(cls.client_id == client_id)

        query = query.order_by(cls.created_at.desc()).limit(limit).offset(offset)

        result = await db_session.execute(query)

        return result.scalars().all()
