from datetime import datetime, timezone
from typing import Optional, List
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.order import Order, OrderStatus
from app.models.cart import Cart
from app.services.inventory_service import InventoryService

logger = logging.getLogger(__name__)


class OrderService:
    """
    Order lifecycle manager AFTER checkout.

    - NO order creation here
    - CheckoutService is the only creator
    """

    def __init__(self, db: AsyncSession):
        if not db:
            raise ValueError("AsyncSession must be provided")
        self.db = db

    # --------------------------------------------------
    # GET ORDER (TENANT SAFE)
    # --------------------------------------------------
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

    # --------------------------------------------------
    # LIST ORDERS (TENANT SAFE)
    # --------------------------------------------------
    async def list(
        self,
        merchant_id: str,
        client_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> List[Order]:
        # FIX: added offset for cursor-style pagination. Fetch limit+1 rows so the
        # caller can detect whether more pages exist without a separate COUNT query.
        # The extra row is sliced off before returning — it is purely a has_more signal.
        stmt = (
            select(Order)
            .where(Order.merchant_id == merchant_id)
            .order_by(Order.created_at.desc())
            .offset(offset)
            .limit(limit + 1)
        )

        if client_id:
            stmt = stmt.where(Order.client_id == client_id)

        if status:
            try:
                stmt = stmt.where(Order.status == OrderStatus(status))
            except ValueError:
                pass

        res = await self.db.execute(stmt)
        rows = res.scalars().all()

        # Trim the extra row — the route layer is responsible for communicating
        # has_more to the client (add a has_more field to the response envelope
        # when you add pagination to the API response schema).
        return rows[:limit]

    # --------------------------------------------------
    # UPDATE STATUS (TENANT SAFE)
    # --------------------------------------------------
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
            extra={
                "order_id": order_id,
                "status": new_status.value,
                "merchant_id": merchant_id,
            },
        )

        return order

    # --------------------------------------------------
    # RESOLVE BY ORDER CODE
    # --------------------------------------------------
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

    # --------------------------------------------------
    # FINALIZE PAYMENT + INVENTORY (IDEMPOTENT)
    # --------------------------------------------------
    async def mark_order_paid_and_finalize_inventory(
        self,
        order_id: str,
    ) -> Order:
        """
        Called AFTER payment success (card webhook OR cash confirmation).

        Atomically:
        - locks order
        - deducts inventory
        - closes cart
        - updates order status
        """

        inventory = InventoryService(self.db)

        result = await self.db.execute(
            select(Order)
            .where(Order.id == order_id)
            .with_for_update()
        )
        order = result.scalars().first()

        if not order:
            raise ValueError("Order not found")

        # Idempotency guard (UPPERCASE enum)
        if order.status in {
            OrderStatus.PAID,
            OrderStatus.AWAITING_PICKUP,
            OrderStatus.FULFILLED,
        }:
            return order

        cart = await self.db.get(Cart, order.cart_id)

        if not cart or not cart.items:
            raise ValueError("Cart missing for order")

        # Deduct inventory exactly once
        for item in cart.items:
            await inventory.finalize_sale(
                merchant_id=order.merchant_id,
                client_id=order.client_id,
                product_id=item.product_id,
                quantity=item.quantity,
            )

        # Close cart
        cart.checked_out = True
        cart.checked_out_at = datetime.now(timezone.utc)

        # Update order status (UPPERCASE)
        if order.payment_method == "cash":
            order.status = OrderStatus.AWAITING_PICKUP
        else:
            order.status = OrderStatus.PAID

        order.confirmed_at = datetime.now(timezone.utc)
        order.updated_at = datetime.now(timezone.utc)

        await self.db.flush()

        logger.info(
            "Order finalized after payment",
            extra={"order_id": order_id, "status": order.status.value},
        )

        return order