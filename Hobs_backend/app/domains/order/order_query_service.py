from typing import Optional, Dict, Any
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.domains.order.models import Order
from app.domains.cart.models import Cart

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
    ) -> Optional[Dict[str, Any]]:

        result = await self.db.execute(
            select(Order).where(
                Order.order_code == order_code,
                Order.merchant_id == merchant_id,
            )
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
