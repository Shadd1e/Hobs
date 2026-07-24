import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.domains.order.models import Order, OrderStatus
from app.domains.cart.models import Cart, CartItem
from app.domains.inventory.inventory_service import InventoryService
from app.domains.payment.payment_service import PaymentService
from app.domains.tenant.models import Client

logger = logging.getLogger(__name__)


class OrderFulfillmentService:
    """
    Confirms cash orders on behalf of the authorised store WhatsApp number.

    Security model:
    - Only the phone number stored in client.confirm_whatsapp_number may confirm.
    - Inventory is deducted HERE (at pickup), not at checkout.
    - Idempotent: calling twice returns success without double-deducting.

    Transaction ownership:
    - Caller owns the transaction boundary (db.begin()).
    - This service only flushes.
    """

    def __init__(self, db: AsyncSession):
        if not db:
            raise ValueError("AsyncSession must be provided")
        self.db = db

    async def confirm_pickup(
        self,
        *,
        order_code: str,
        from_whatsapp_number: str,
    ) -> Order:
        """
        Called when the store's WhatsApp number sends 'confirm ORDERCODE'.

        Steps:
        1. Load and lock order.
        2. Verify sender is the authorised store number.
        3. Confirm cash payment record.
        4. Deduct inventory (first time only — idempotency guard on order status).
        5. Close cart.
        6. Transition order → FULFILLED.
        """

        # 1. Lock order
        result = await self.db.execute(
            select(Order)
            .where(Order.order_code == order_code)
            .with_for_update()
        )
        order: Optional[Order] = result.scalars().first()

        if not order:
            raise ValueError(f"Order {order_code} not found")

        if order.payment_method != "cash":
            raise ValueError("Only cash orders can be confirmed via WhatsApp")

        # 2. Idempotency guard
        if order.status == OrderStatus.FULFILLED:
            logger.info("Order %s already fulfilled — idempotent return", order_code)
            return order

        if order.status not in (OrderStatus.AWAITING_PICKUP, OrderStatus.CREATED):
            raise ValueError(
                f"Order {order_code} cannot be confirmed (current status: {order.status.value})"
            )

        # 3. Verify authorised store number
        result = await self.db.execute(
            select(Client).where(Client.id == order.client_id)
        )
        client: Optional[Client] = result.scalars().first()

        if not client:
            raise ValueError("Client not found for order")

        if not client.confirm_whatsapp_number:
            raise ValueError(
                "This store has not configured a confirmation WhatsApp number. "
                "Contact support to set up confirm_whatsapp_number."
            )

        if not client.is_store_number(from_whatsapp_number):
            logger.warning(
                "Unauthorised confirmation attempt for order %s from %s",
                order_code,
                from_whatsapp_number,
            )
            raise ValueError("Unauthorised: this number is not allowed to confirm orders")

        # 4. Confirm the payment record
        payment_service = PaymentService(self.db)
        await payment_service.confirm_cash_payment(
            order=order,
            merchant_id=order.merchant_id,
            client_id=order.client_id,
        )

        # 5. Deduct inventory (cash: deduct at pickup)
        result = await self.db.execute(
            select(Cart)
            .where(Cart.id == order.cart_id)
            .options(selectinload(Cart.items).selectinload(CartItem.product))
        )
        cart: Optional[Cart] = result.scalars().first()

        if not cart:
            raise ValueError("Cart not found for order — cannot deduct inventory")

        inventory_service = InventoryService(self.db)
        for item in cart.items:
            await inventory_service.finalize_sale(
                merchant_id=order.merchant_id,
                client_id=order.client_id,
                product_id=item.product_id,
                quantity=item.quantity,
            )

        # 6. Close cart
        if not cart.checked_out:
            cart.checked_out = True
            cart.checked_out_at = datetime.now(timezone.utc)

        # 7. Transition order to FULFILLED
        await order.transition_to(OrderStatus.FULFILLED, self.db)

        await self.db.flush()

        logger.info(
            "Cash order fulfilled",
            extra={
                "order_code": order_code,
                "order_id": order.id,
                "confirmed_by": from_whatsapp_number,
            },
        )

        return order
