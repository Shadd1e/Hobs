# app/domains/order/checkout_service.py

import logging
from uuid import uuid4
from typing import Optional
from datetime import datetime, timezone
from decimal import Decimal
import httpx
import os

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from sqlalchemy.orm import selectinload

from app.domains.payment.models import PaymentStatus
from app.domains.cart.models import Cart, CartItem
from app.domains.order.models import Order, OrderStatus
from app.domains.product.models import Product
from app.schemas.checkout import CheckoutRequestSchema, CheckoutResponseSchema
from app.domains.payment.payment_service import PaymentService
from app.domains.inventory.inventory_service import InventoryService
from app.domains.cart.cart_service import CartService
from app.core.helpers import number_to_words
from app.shared.models import generate_uuid

logger = logging.getLogger(__name__)


class CheckoutService:
    """
    Pure domain service. No transaction ownership.
    Caller (orchestrator / API route) owns begin/commit/rollback.

    Inventory deduction policy:
    - card:  deducted immediately at checkout (reversed if payment fails)
    - cash:  NOT deducted here — deducted at pickup confirmation
    """

    def __init__(self, db: AsyncSession):
        if not db:
            raise ValueError("AsyncSession required")
        self.db = db
        self.payment_service = PaymentService(db)
        self.inventory_service = InventoryService(db)
        self.cart_service = CartService(db)

    # ==================================================
    # PUBLIC ENTRYPOINT
    # ==================================================

    async def checkout(self, data: CheckoutRequestSchema) -> CheckoutResponseSchema:
        if not data.merchant_id or not data.client_id or not data.user_id:
            raise ValueError("Missing tenant context")
        if not data.cart_id:
            raise ValueError("cart_id is required")
        return await self._checkout_internal(data)

    # ==================================================
    # INTERNAL CHECKOUT LOGIC
    # ==================================================

    async def _checkout_internal(self, data: CheckoutRequestSchema) -> CheckoutResponseSchema:

        # Lock cart row first
        lock = await self.db.execute(
            text("SELECT id FROM carts WHERE id = :id FOR UPDATE"),
            {"id": str(data.cart_id)},
        )
        if not lock.first():
            raise ValueError("Cart not found")

        # Fetch cart with relations
        result = await self.db.execute(
            select(Cart)
            .where(
                Cart.id == data.cart_id,
                Cart.merchant_id == data.merchant_id,
                Cart.client_id == data.client_id,
                Cart.user_id == data.user_id,
            )
            .options(
                selectinload(Cart.items)
                .selectinload(CartItem.product)
                .selectinload(Product.inventory)
            )
        )
        cart = result.scalars().first()

        if not cart:
            raise ValueError("Cart not found for tenant")
        if not cart.items:
            raise ValueError("Cannot checkout empty cart")

        # Calculate total
        total = sum(
            Decimal(str(i.price_at_add)) * Decimal(str(i.quantity))
            for i in cart.items
        )
        total_float = float(total)
        total_words = number_to_words(total_float)

        # -------------------------------------------------------
        # The unique constraint uq_order_per_cart means only ONE
        # order row can ever exist per cart_id, regardless of status.
        # We must check for ANY existing order and handle each case:
        #   PENDING_PAYMENT -> reuse: regenerate payment link
        #   PAID/FULFILLED  -> already done, tell customer
        #   CANCELLED       -> safe to delete and create fresh order
        # -------------------------------------------------------
        existing_order_result = await self.db.execute(
            select(Order).where(
                Order.cart_id == data.cart_id,
                Order.merchant_id == data.merchant_id,
                Order.client_id == data.client_id,
                Order.user_id == data.user_id,
            ).with_for_update()
        )
        existing_order = existing_order_result.scalars().first()

        if existing_order:
            if existing_order.status == OrderStatus.PENDING_PAYMENT and data.payment_method == "card":
                # Reuse: just regenerate the Paystack link
                logger.info(
                    "Reusing existing PENDING_PAYMENT order %s for cart %s",
                    existing_order.id,
                    data.cart_id,
                )
                reference = f"order_{existing_order.id}"
                from app.services.paystack_subaccount_service import PaystackSubaccountService
                sub_service = PaystackSubaccountService(self.db)
                subaccount_code = await sub_service.get_subaccount_code(
                    client_id=cart.client_id,
                    merchant_id=cart.merchant_id,
                )
                payment_link = await self.create_paystack_payment_link(
                    reference=reference,
                    amount_naira=float(existing_order.total_amount),
                    phone=data.user_id,
                    subaccount_code=subaccount_code,
                )
                return CheckoutResponseSchema(
                    success=True,
                    order_id=str(existing_order.id),
                    order_code=existing_order.order_code,
                    order_status=existing_order.status.value,
                    message=(
                        f"Order placed successfully!\n"
                        f"Total: {total_words} Naira\n"
                        f"Order Code: {existing_order.order_code}"
                    ),
                    total_amount=float(existing_order.total_amount),
                    payment_instructions=None,
                    estimated_time="30–45 minutes",
                    store_contact="Store",
                    payment_link=payment_link,
                )

            elif existing_order.status in (OrderStatus.PAID, OrderStatus.FULFILLED, OrderStatus.AWAITING_PICKUP):
                # Already completed — don't allow re-checkout
                raise ValueError(
                    f"This cart already has a completed order ({existing_order.order_code}). "
                    f"Status: {existing_order.status.value}"
                )

            elif existing_order.status == OrderStatus.CANCELLED:
                # Cancelled order blocks the unique constraint — delete it so we can create fresh
                logger.info(
                    "Deleting CANCELLED order %s to allow re-checkout for cart %s",
                    existing_order.id,
                    data.cart_id,
                )
                await self.db.delete(existing_order)
                await self.db.flush()
                # Reset cart so the rest of the flow proceeds normally
                cart.checked_out = False
                cart.checked_out_at = None

            # PENDING_PAYMENT + cash, or CREATED: fall through to create new order below

        if cart.checked_out:
            raise ValueError("Cart already checked out")

        # Availability check (non-locking — real lock happens at finalize_sale for card)
        for item in cart.items:
            inv = item.product.inventory if item.product else None
            if not inv or inv.quantity < item.quantity:
                raise ValueError(
                    f"Insufficient stock for {item.product.name if item.product else 'item'}"
                )

        # Initial order status
        if data.payment_method == "card":
            initial_status = OrderStatus.PENDING_PAYMENT
        elif data.payment_method == "cash":
            initial_status = OrderStatus.AWAITING_PICKUP
        else:
            initial_status = OrderStatus.CREATED

        # Create order
        order = Order(
            id=generate_uuid(),
            cart_id=cart.id,
            merchant_id=cart.merchant_id,
            client_id=cart.client_id,
            user_id=data.user_id,
            customer_name=data.customer_name,
            payment_method=data.payment_method,
            total_amount=total_float,
            order_code=str(uuid4())[:8].upper(),
            status=initial_status,
        )
        self.db.add(order)
        await self.db.flush()

        payment_link = None

        # Create payment record
        if data.payment_method == "card":
            reference = f"order_{order.id}"

            from app.services.paystack_subaccount_service import PaystackSubaccountService
            sub_service = PaystackSubaccountService(self.db)
            subaccount_code = await sub_service.get_subaccount_code(
                client_id=cart.client_id,
                merchant_id=cart.merchant_id,
            )

            await self.payment_service.create_paystack_payment(
                order_id=str(order.id),
                merchant_id=cart.merchant_id,
                client_id=cart.client_id,
                amount=Decimal(str(total_float)),
                reference=reference,
                customer_phone=data.user_id,
            )

            payment_link = await self.create_paystack_payment_link(
                reference=reference,
                amount_naira=total_float,
                phone=data.user_id,
                subaccount_code=subaccount_code,
            )

            # Card: deduct inventory immediately (will be reversed on payment failure)
            for item in cart.items:
                await self.inventory_service.finalize_sale(
                    merchant_id=cart.merchant_id,
                    client_id=cart.client_id,
                    product_id=item.product_id,
                    quantity=item.quantity,
                )

            # Close cart for card payments immediately
            cart.checked_out = True
            cart.checked_out_at = datetime.now(timezone.utc)

        elif data.payment_method == "cash":
            # Cash: create pending payment — inventory deducted at pickup confirmation
            await self.payment_service.create_cash_payment(
                order_id=str(order.id),
                merchant_id=cart.merchant_id,
                client_id=cart.client_id,
                amount=Decimal(str(total_float)),
                customer_name=data.customer_name,
            )
            # Do NOT close cart or deduct inventory yet — that happens at pickup

        else:
            from app.schemas.payment import PaymentCreate
            await self.payment_service.create(
                PaymentCreate(
                    order_id=str(order.id),
                    merchant_id=cart.merchant_id,
                    client_id=cart.client_id,
                    amount=total_float,
                    method=data.payment_method,
                    status=PaymentStatus.PENDING,
                )
            )

        return CheckoutResponseSchema(
            success=True,
            order_id=str(order.id),
            order_code=order.order_code,
            order_status=order.status.value,
            message=(
                f"Order placed successfully!\n"
                f"Total: {total_words} Naira\n"
                f"Order Code: {order.order_code}"
            ),
            total_amount=total_float,
            payment_instructions=None,
            estimated_time="30–45 minutes",
            store_contact="Store",
            payment_link=payment_link,
        )

    # ==================================================
    # WHATSAPP WRAPPER
    # ==================================================

    async def checkout_from_whatsapp(
        self,
        *,
        merchant_id: str,
        client_id: str,
        user_id: str,
        payment_method: str,
        customer_name: Optional[str] = None,
        tenant_context=None,
    ) -> CheckoutResponseSchema:

        cart = await self.cart_service.get_active_cart(
            merchant_id=merchant_id,
            client_id=client_id,
            user_id=user_id,
        )

        if not cart:
            raise ValueError("No active cart found.")

        checkout_data = CheckoutRequestSchema(
            cart_id=str(cart.id),
            merchant_id=merchant_id,
            client_id=client_id,
            user_id=user_id,
            payment_method=payment_method,
            customer_name=customer_name or "WhatsApp Customer",
            pickup_location=None,
        )

        return await self.checkout(checkout_data)

    # ==================================================
    # PAYSTACK EXTERNAL CALL
    # ==================================================

    async def create_paystack_payment_link(
        self,
        *,
        reference: str,
        amount_naira: float,
        phone: str,
        subaccount_code: Optional[str] = None,
    ) -> str:
        secret = os.getenv("PAYSTACK_SECRET_KEY")
        if not secret:
            raise ValueError("PAYSTACK_SECRET_KEY not configured")
        redirect_url = os.getenv("PAYSTACK_REDIRECT_URL", "")
        amount_kobo = int(amount_naira * 100)
        payload = {
            "reference": reference,
            "amount": amount_kobo,
            "currency": "NGN",
            "callback_url": redirect_url,
            "customer": {
                "phone": phone,
                "email": f"{phone.replace('+', '')}@shopprhq.app",
            },
            "channels": ["card", "bank", "ussd", "bank_transfer", "mobile_money"],
        }
        if subaccount_code:
            payload["subaccount"] = subaccount_code
            payload["bearer"] = "subaccount"
        headers = {
            "Authorization": f"Bearer {secret}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                "https://api.paystack.co/transaction/initialize",
                json=payload,
                headers=headers,
            )
        if response.status_code != 200:
            logger.error("Paystack init error %s: %s", response.status_code, response.text)
            raise ValueError("Failed to initialize Paystack payment")
        data = response.json()
        url = data.get("data", {}).get("authorization_url")
        if not url:
            raise ValueError("Paystack did not return authorization_url")
        return url
