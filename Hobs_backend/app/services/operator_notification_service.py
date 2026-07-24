# app/services/operator_notification_service.py
"""
Sends WhatsApp notifications to the store operator.

Rules:
- Never raises — all failures are logged and swallowed
- Always fires AFTER the DB transaction commits (call outside db.begin())
- Uses the same send_whatsapp_message infrastructure as customer notifications
- Requires operator_notify_phone to be set on the Client record
"""

import logging
from typing import Optional
from decimal import Decimal

from app.services.whatsapp_sender import send_whatsapp_message

logger = logging.getLogger(__name__)


class OperatorNotificationService:

    def __init__(
        self,
        *,
        operator_phone: Optional[str],
        phone_number_id: str,
        store_name: str,
    ):
        self.operator_phone = operator_phone
        self.phone_number_id = phone_number_id
        self.store_name = store_name

    def _ready(self) -> bool:
        """Only send if operator phone is configured."""
        if not self.operator_phone:
            logger.debug("Operator notifications skipped — no operator_notify_phone set")
            return False
        return True

    async def _send(self, message: str) -> None:
        """Send with full error swallowing — operator notifications must never crash the main flow."""
        if not self._ready():
            return
        try:
            await send_whatsapp_message(
                to_number=self.operator_phone,
                message=message,
                phone_number_id=self.phone_number_id,
            )
            logger.info("Operator notified — phone=%s", self.operator_phone)
        except Exception as e:
            logger.error("Operator notification failed: %s", e)

    # =====================================================
    # NEW ORDER PING (ALL PAYMENT TYPES)
    # Simple one-line alert sent the moment any order is placed.
    # Operator can reply with just the order code to see full details.
    # =====================================================

    async def new_order_ping(
        self,
        *,
        order_code: str,
        payment_method: str,
        total: float,
    ) -> None:
        """
        Fire a minimal, instant alert for every new order regardless of
        payment method.  Keeps it to one line so it reads like a push
        notification — operator replies with the order code to see detail.
        """
        method_label = {
            "cash":           "Cash 💵",
            "card":           "Card 💳",
            "bank_transfer":  "Transfer 🏦",
            "whatsapp_payment": "WhatsApp Pay",
        }.get(payment_method, payment_method.replace("_", " ").title())

        message = (
            f"🛒 New order at *{self.store_name}*\n"
            f"Payment: {method_label} · ₦{total:,.0f}\n"
            f"Code: *{order_code}*\n\n"
            f"Reply *{order_code}* to see the full order."
        )
        await self._send(message)

    # =====================================================
    # CASH ORDER PLACED
    # =====================================================

    async def cash_order_placed(
        self,
        *,
        order_code: str,
        customer_phone: str,
        total: float,
        items_summary: str,
        delivery_type: str = "pickup",
        delivery_address: Optional[str] = None,
        delivery_contact: Optional[str] = None,
    ) -> None:
        """Notify operator a new cash order has been placed."""
        is_delivery = delivery_type == "delivery"
        type_line   = "🛵 *Delivery*" if is_delivery else "📦 *Pickup*"

        delivery_lines = ""
        if is_delivery and delivery_address:
            delivery_lines += f"Address: _{delivery_address}_\n"
        if is_delivery and delivery_contact:
            delivery_lines += f"Contact: +{delivery_contact.lstrip('+')}\n"
        if delivery_lines:
            delivery_lines = "\n" + delivery_lines

        cta = (
            f"Prepare and dispatch when ready. Reply *confirm {order_code}* once delivered."
            if is_delivery
            else f"Reply *confirm {order_code}* when cash payment is received."
        )

        message = (
            f"🛒 *New Order — {self.store_name}*\n\n"
            f"Order Code: *{order_code}*\n"
            f"Type: {type_line}\n"
            f"Customer: +{customer_phone.lstrip('+')}\n"
            f"Total: ₦{total:,.2f}"
            f"{delivery_lines}\n"
            f"Items:\n{items_summary}\n\n"
            f"{cta}"
        )
        await self._send(message)

    # =====================================================
    # CARD PAYMENT CONFIRMED
    # =====================================================

    async def card_payment_confirmed(
        self,
        *,
        order_code: str,
        customer_phone: str,
        total: float,
        items_summary: str,
        delivery_type: str = "pickup",
        delivery_address: Optional[str] = None,
        delivery_contact: Optional[str] = None,
    ) -> None:
        """Notify operator a card payment has been confirmed and order is ready to fulfil."""
        is_delivery = delivery_type == "delivery"
        type_line   = "🛵 *Delivery*" if is_delivery else "📦 *Pickup*"

        delivery_lines = ""
        if is_delivery and delivery_address:
            delivery_lines += f"Address: _{delivery_address}_\n"
        if is_delivery and delivery_contact:
            delivery_lines += f"Contact: +{delivery_contact.lstrip('+')}\n"
        if delivery_lines:
            delivery_lines = "\n" + delivery_lines

        action = (
            "Prepare and dispatch to the customer's address."
            if is_delivery
            else "Please prepare this order for pickup."
        )

        message = (
            f"✅ *Card Payment Confirmed — {self.store_name}*\n\n"
            f"Order Code: *{order_code}*\n"
            f"Type: {type_line}\n"
            f"Customer: +{customer_phone.lstrip('+')}\n"
            f"Total: ₦{total:,.2f}"
            f"{delivery_lines}\n"
            f"Items:\n{items_summary}\n\n"
            f"{action}"
        )
        await self._send(message)

    # =====================================================
    # LOW STOCK WARNING
    # =====================================================

    async def low_stock_warning(
        self,
        *,
        product_name: str,
        remaining: int,
        threshold: int,
    ) -> None:
        """Notify operator a product has dropped to or below the low stock threshold."""
        message = (
            f"⚠️ *Low Stock Alert — {self.store_name}*\n\n"
            f"Product: *{product_name}*\n"
            f"Remaining: *{remaining}* unit{'s' if remaining != 1 else ''}\n"
            f"Threshold: {threshold}\n\n"
            f"Please restock soon to avoid running out."
        )
        await self._send(message)

    # =====================================================
    # OUT OF STOCK
    # =====================================================

    async def out_of_stock(self, *, product_name: str) -> None:
        """Notify operator a product has hit zero stock."""
        message = (
            f"🚨 *Out of Stock — {self.store_name}*\n\n"
            f"*{product_name}* is now out of stock.\n\n"
            f"Update inventory to resume sales of this product."
        )
        await self._send(message)
