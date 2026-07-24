from typing import Optional, Dict, Any
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.order import Order
from app.models.cart import Cart

logger = logging.getLogger(__name__)


class OrderQueryService:
    """
    Read-only order lookup by order_code.
    Safe for WhatsApp, staff tools, dashboards.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_order_by_code(
        self,
        order_code: str,
        merchant_id: str,
        user_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Look up an order by code.
        When user_id is supplied (WhatsApp customer flow), the result is
        scoped to that customer so no one can read another customer's
        order by guessing a code. Omit user_id for operator/dashboard lookups.
        """
        from sqlalchemy import and_
        filters = [
            Order.order_code == order_code,
            Order.merchant_id == merchant_id,
        ]
        if user_id:
            # Normalise — strip + so +234... and 234... both match
            filters.append(Order.user_id == user_id.lstrip("+").strip())

        result = await self.db.execute(
            select(Order).where(and_(*filters))
        )
        order = result.scalars().first()

        if not order:
            return None

        items = []

        if order.cart_id:
            result = await self.db.execute(
                select(Cart)
                .where(Cart.id == order.cart_id)
                .options(selectinload(Cart.items))
            )
            cart = result.scalars().first()

            if cart:
                for item in cart.items:
                    items.append({
                        "product_id": str(item.product_id),
                        "quantity": item.quantity,
                        "unit_price": item.price_at_add,
                        "subtotal": item.price_at_add * item.quantity,
                    })

        return {
            "order_code": order.order_code,
            "status": order.status.value,
            "payment_method": order.payment_method,
            "total_amount": order.total_amount,
            "customer_name": order.customer_name,
            "created_at": order.created_at,
            "confirmed_at": order.confirmed_at,
            "items": items,
        }
