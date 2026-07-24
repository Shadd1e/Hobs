from datetime import datetime, timezone
from typing import Optional, List
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.domains.order.models import Order, OrderStatus
from app.domains.cart.models import Cart, CartItem

logger = logging.getLogger(__name__)


class OrderService:
    """
    Order lifecycle manager AFTER checkout.
    CheckoutService is the only order creator.
    """

    def __init__(self, db: AsyncSession):
        if not db:
            raise ValueError("AsyncSession must be provided")
        self.db = db

    async def get(
        self,
        order_id: str,
        merchant_id: str,
        client_id: Optional[str] = None,
    ) -> Optional[Order]:
        stmt = select(Order).where(
            Order.id == order_id,
            Order.merchant_id == merchant_id,
        )
        if client_id:
            stmt = stmt.where(Order.client_id == client_id)
        res = await self.db.execute(stmt)
        return res.scalars().first()

    async def list(
        self,
        merchant_id: str,
        client_id: Optional[str] = None,
    ) -> List[Order]:
        stmt = select(Order).where(Order.merchant_id == merchant_id)
        if client_id:
            stmt = stmt.where(Order.client_id == client_id)
        res = await self.db.execute(stmt)
        return res.scalars().all()

    async def update_status(
        self,
        order_id: str,
        new_status: OrderStatus,
        merchant_id: str,
        client_id: Optional[str] = None,
    ) -> Optional[Order]:
        stmt = select(Order).where(
            Order.id == order_id,
            Order.merchant_id == merchant_id,
        )
        if client_id:
            stmt = stmt.where(Order.client_id == client_id)

        res = await self.db.execute(stmt)
        order = res.scalars().first()
        if not order:
            return None

        order.status = new_status
        order.updated_at = datetime.now(timezone.utc)
        await self.db.flush()

        logger.info(
            "Order status updated",
            extra={"order_id": order_id, "status": new_status.value, "merchant_id": merchant_id},
        )
        return order

    async def get_by_order_code(
        self,
        order_code: str,
        merchant_id: str,
    ) -> Optional[Order]:
        res = await self.db.execute(
            select(Order).where(
                Order.order_code == order_code,
                Order.merchant_id == merchant_id,
            )
        )
        return res.scalars().first()

    async def mark_order_paid_and_finalize_inventory(self, order_id: str) -> Order:
        """
        Called AFTER card payment webhook confirmation.
        Inventory was already deducted at checkout for card payments.
        This method only updates order status.
        """
        from app.domains.inventory.inventory_service import InventoryService

        result = await self.db.execute(
            select(Order)
            .where(Order.id == order_id)
            .with_for_update()
        )
        order = result.scalars().first()

        if not order:
            raise ValueError("Order not found")

        # Idempotency guard
        if order.status in {OrderStatus.PAID, OrderStatus.AWAITING_PICKUP, OrderStatus.FULFILLED}:
            return order

        # For card orders, inventory already deducted at checkout.
        # Just update status.
        await order.transition_to(OrderStatus.PAID, self.db)
        await self.db.flush()

        logger.info(
            "Order marked paid",
            extra={"order_id": order_id, "status": order.status.value},
        )
        return order
