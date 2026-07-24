import logging
logger = logging.getLogger(__name__)

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.models.order import Order, OrderStatus
from app.models.client_model import Client
from app.models.cart import Cart, CartItem
from sqlalchemy.orm import selectinload


class OrderFulfillmentService:
    """
    Handles two fulfillment events:

    1. confirm_pickup  — cash order collected / delivered. Marks FULFILLED.
       Accepts AWAITING_PICKUP (pickup orders) and OUT_FOR_DELIVERY (delivery orders).

    2. mark_out_for_delivery — merchant dispatches a delivery order.
       Transitions AWAITING_PICKUP → OUT_FOR_DELIVERY and notifies the customer.

    RULES:
    - Only CASH orders flow through here (card payments are handled by Flutterwave webhook)
    - Idempotent — safe to call twice
    - Does NOT open its own transaction — caller owns the boundary
    """

    def __init__(self, db: AsyncSession):
        if not db:
            raise ValueError("AsyncSession must be provided")
        self.db = db

    # ==================================================
    # MARK OUT FOR DELIVERY
    # ==================================================

    async def mark_out_for_delivery(
        self,
        *,
        order_id: str,
        merchant_id: str,
    ) -> Optional[dict]:
        """
        Transition a paid/awaiting delivery order to OUT_FOR_DELIVERY
        and return the data needed to notify the customer via WhatsApp.

        Returns:
            dict with order_code, user_phone, delivery_contact_number,
                  client_id, phone_number_id
            None if order was already OUT_FOR_DELIVERY (idempotent)

        Raises:
            ValueError  — business rule violation
            RuntimeError — DB failure
        """
        try:
            result = await self.db.execute(
                select(Order)
                .where(Order.id == order_id, Order.merchant_id == merchant_id)
                .with_for_update()
            )
            order: Optional[Order] = result.scalar_one_or_none()

            if not order:
                raise ValueError("Order not found")

            if not order.is_delivery_order:
                raise ValueError("This is not a delivery order")

            # Idempotent
            if order.status == OrderStatus.OUT_FOR_DELIVERY:
                logger.info("Order %s already out for delivery — skipping", order.order_code)
                return None

            # Must be in a dispatchable state
            if order.status not in (OrderStatus.AWAITING_PICKUP, OrderStatus.PAID):
                raise ValueError(
                    f"Cannot dispatch — current status: {order.status.value}"
                )

            order.status       = OrderStatus.OUT_FOR_DELIVERY
            order.dispatched_at = datetime.now(timezone.utc)
            await self.db.flush()

            logger.info(
                "🚴 Order %s marked OUT_FOR_DELIVERY",
                order.order_code,
                extra={"order_id": order_id, "merchant_id": merchant_id},
            )

            # Resolve phone_number_id for WhatsApp notification
            from app.models.client_whatsapp_credential import ClientWhatsAppCredential
            cred_result = await self.db.execute(
                select(ClientWhatsAppCredential).where(
                    ClientWhatsAppCredential.client_id == order.client_id,
                    ClientWhatsAppCredential.active.is_(True),
                )
            )
            cred = cred_result.scalar_one_or_none()

            return {
                "order_code":             order.order_code,
                "user_phone":             order.user_id,
                "delivery_contact_number": order.delivery_contact_number,
                "client_id":              order.client_id,
                "phone_number_id":        cred.phone_number_id if cred else None,
            }

        except (ValueError, RuntimeError):
            raise
        except SQLAlchemyError as e:
            raise RuntimeError(f"Failed to mark out for delivery: {e}") from e

    # ==================================================
    # CONFIRM PICKUP / DELIVERY RECEIPT
    # ==================================================

    async def confirm_pickup(
        self,
        order_code: str,
        from_whatsapp_number: str,
    ) -> Optional[dict]:
        """
        Validates and fulfils a cash order (pickup or delivery).

        Accepts orders in:
          - AWAITING_PICKUP  (pickup orders waiting at store)
          - OUT_FOR_DELIVERY (delivery orders already dispatched)

        Returns receipt dict on success.
        Returns None if the order was already fulfilled (idempotent).
        Raises ValueError for business-rule violations.
        Raises RuntimeError for DB errors.
        """
        try:
            result = await self.db.execute(
                select(Order)
                .where(Order.order_code == order_code)
                .with_for_update()
            )
            order: Optional[Order] = result.scalars().first()

            if not order:
                raise ValueError("Order not found")

            if order.payment_method != "cash":
                raise ValueError("Only cash orders can be confirmed this way")

            # Idempotent
            if order.status == OrderStatus.FULFILLED:
                logger.info("Order %s already fulfilled — skipping", order_code)
                return None

            ready_statuses = (OrderStatus.AWAITING_PICKUP, OrderStatus.OUT_FOR_DELIVERY)
            if order.status not in ready_statuses:
                raise ValueError(
                    f"Order cannot be confirmed — current status: {order.status.value}"
                )

            # ── Auth: only the registered operator can confirm ─────────────────
            client_result = await self.db.execute(
                select(Client).where(Client.id == order.client_id)
            )
            client: Optional[Client] = client_result.scalars().first()

            if not client:
                raise ValueError("Store not found")

            if not client.operator_notify_phone:
                raise ValueError(
                    "No operator phone configured for this store. "
                    "Set it via the dashboard Settings page."
                )

            incoming = from_whatsapp_number.replace("+", "").strip()
            allowed  = client.operator_notify_phone.replace("+", "").strip()

            if incoming != allowed:
                raise ValueError("Unauthorized pickup confirmation")

            # ── Resolve phone_number_id ───────────────────────────────────────
            from app.models.client_whatsapp_credential import ClientWhatsAppCredential
            cred_result = await self.db.execute(
                select(ClientWhatsAppCredential).where(
                    ClientWhatsAppCredential.client_id == order.client_id,
                    ClientWhatsAppCredential.active.is_(True),
                )
            )
            cred = cred_result.scalar_one_or_none()
            phone_number_id = cred.phone_number_id if cred else None

            # ── Fulfil ────────────────────────────────────────────────────────
            order.status      = OrderStatus.FULFILLED
            order.confirmed_at = datetime.now(timezone.utc)
            await self.db.flush()

            logger.info(
                "✅ Cash order fulfilled",
                extra={
                    "order_code": order_code,
                    "order_id":   str(order.id),
                    "client_id":  order.client_id,
                },
            )

            # ── Load cart items for receipt ────────────────────────────────────
            cart_result = await self.db.execute(
                select(Cart)
                .where(Cart.id == order.cart_id)
                .options(selectinload(Cart.items).selectinload(CartItem.product))
            )
            cart  = cart_result.scalar_one_or_none()
            items = cart.items if cart else []

            return {
                "order_code":      order.order_code,
                "user_phone":      order.user_id,
                "total_amount":    float(order.total_amount),
                "client_id":       order.client_id,
                "phone_number_id": phone_number_id,
                "items": [
                    {
                        "name":     getattr(i.product, "name", str(i.product_id)),
                        "quantity": i.quantity,
                        "price":    float(i.price_at_add),
                    }
                    for i in items
                ],
            }

        except (ValueError, RuntimeError):
            raise
        except SQLAlchemyError as e:
            raise RuntimeError(f"Failed to confirm pickup: {e}") from e
