# app/services/checkout_service.py

import logging
from typing import Optional
from datetime import datetime, timezone
from decimal import Decimal
import httpx
import os

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from sqlalchemy.orm import selectinload

from app.models.payment import PaymentStatus
from app.models.cart import Cart, CartItem
from app.models.order import Order, OrderStatus, DeliveryType, generate_order_code
from app.models.product import Product
from app.models.client_model import Client as ClientModel
from app.schemas.checkout import CheckoutRequestSchema, CheckoutResponseSchema
from app.schemas.payment import PaymentCreate
from app.services.payment_service import PaymentService
from app.services.inventory_service import InventoryService
from app.services.cart_service import CartService
from app.core.helpers import number_to_words
from app.models.utils import generate_uuid
from app.services.paystack_subaccount_service import PaystackSubaccountService

logger = logging.getLogger(__name__)


class CheckoutService:
    """
    Pure domain service.

    RULES:
    - NO transaction ownership
    - NO commit()
    - NO rollback()
    - Caller (orchestrator) owns transaction boundary
    """

    def __init__(self, db: AsyncSession):
        if not db:
            raise ValueError("AsyncSession required")

        self.db = db
        self.payment_service    = PaymentService(db)
        self.inventory_service  = InventoryService(db)
        self.cart_service       = CartService(db)

    # ==================================================
    # PUBLIC ENTRYPOINT
    # ==================================================

    async def checkout(
        self,
        data: CheckoutRequestSchema,
    ) -> CheckoutResponseSchema:

        if not data.merchant_id or not data.client_id or not data.user_id:
            raise ValueError("Missing tenant context")

        if not data.cart_id:
            raise ValueError("cart_id is required")

        return await self._checkout_internal(data)

    # ==================================================
    # INTERNAL CHECKOUT LOGIC
    # ==================================================

    async def _checkout_internal(
        self,
        data: CheckoutRequestSchema,
    ) -> CheckoutResponseSchema:

        # ----------------------------
        # LOCK CART ROW
        # ----------------------------
        lock = await self.db.execute(
            text("SELECT id FROM carts WHERE id = :id FOR UPDATE"),
            {"id": data.cart_id},
        )

        if not lock.first():
            raise ValueError("Cart not found")

        # ----------------------------
        # FETCH CART WITH RELATIONS
        # ----------------------------
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

        if cart.checked_out:
            raise ValueError("Cart already checked out")

        # Idempotency guard — heal checked_out flag if order already exists
        existing_order_result = await self.db.execute(
            select(Order).where(Order.cart_id == cart.id).limit(1)
        )
        if existing_order_result.scalars().first():
            if not cart.checked_out:
                cart.checked_out = True
                cart.checked_out_at = datetime.now(timezone.utc)
                await self.db.flush()
                logger.info("Healed checked_out flag for cart %s", cart.id)
            raise ValueError("Cart already has an active order")

        if not cart.items:
            raise ValueError("Cannot checkout empty cart")

        # ----------------------------
        # INVENTORY VALIDATION & DEDUCTION (LOCKED)
        # Lock each inventory row and deduct stock atomically for ALL payment
        # methods. Previously this was a read-only check (no FOR UPDATE) and
        # deduction only happened in the Flutterwave webhook — meaning every
        # cash order bypassed stock deduction entirely.
        # ----------------------------
        for item in cart.items:
            try:
                await self.inventory_service.finalize_sale(
                    merchant_id=data.merchant_id,
                    client_id=data.client_id,
                    product_id=str(item.product_id),
                    quantity=item.quantity,
                )
            except ValueError as inv_err:
                product_name = (
                    item.product.name
                    if hasattr(item, "product") and item.product
                    else str(item.product_id)
                )
                raise ValueError(
                    f"Insufficient stock for '{product_name}': {inv_err}"
                ) from inv_err

        # ----------------------------
        # CALCULATE ITEM TOTAL
        # ----------------------------
        items_total = sum(
            Decimal(str(i.price_at_add)) * Decimal(str(i.quantity))
            for i in cart.items
        )

        # ----------------------------
        # DELIVERY FEE
        # ----------------------------
        delivery_fee = Decimal("0")
        delivery_type_value = None

        if data.delivery_type == "delivery":
            delivery_type_value = DeliveryType.DELIVERY
            if data.delivery_fee is not None:
                delivery_fee = Decimal(str(data.delivery_fee))
        elif data.delivery_type == "pickup":
            delivery_type_value = DeliveryType.PICKUP

        grand_total   = items_total + delivery_fee
        total_float   = float(grand_total)
        total_words   = number_to_words(total_float)

        # ----------------------------
        # ORDER STATUS
        # ----------------------------
        if data.payment_method == "card":
            initial_status = OrderStatus.PENDING_PAYMENT
        elif data.payment_method in {"cash", "wishlist"}:
            if delivery_type_value == DeliveryType.DELIVERY:
                initial_status = OrderStatus.AWAITING_PICKUP
            else:
                initial_status = OrderStatus.AWAITING_PICKUP
        else:
            initial_status = OrderStatus.CREATED

        # ----------------------------
        # CREATE ORDER
        # ----------------------------
        order = Order(
            id=generate_uuid(),
            cart_id=cart.id,
            merchant_id=cart.merchant_id,
            client_id=cart.client_id,
            user_id=data.user_id,
            customer_name=data.customer_name,
            payment_method=data.payment_method,
            total_amount=float(grand_total),
            order_code=generate_order_code(),
            status=initial_status,
            delivery_type=delivery_type_value,
            delivery_address=data.delivery_address or None,
            delivery_contact_number=data.delivery_contact_number or None,
            delivery_fee=float(delivery_fee) if delivery_fee else None,
        )

        self.db.add(order)
        await self.db.flush()

        payment_link = None

        # ----------------------------
        # CREATE PAYMENT RECORD
        # ----------------------------
        if data.payment_method == "card":

            reference = f"order_{order.id}"

            await self.payment_service.create_paystack_payment(
                order_id=str(order.id),
                merchant_id=cart.merchant_id,
                client_id=cart.client_id,
                amount=Decimal(str(total_float)),
                reference=reference,
                customer_phone=data.user_id,
            )

            subaccount_service = PaystackSubaccountService(self.db)
            subaccount_code = await subaccount_service.get_subaccount_code(
                client_id=cart.client_id,
                merchant_id=cart.merchant_id,
            )

            try:
                # Look up the store's WhatsApp number so the payment-success
                # page can deep-link the customer back to the right conversation.
                client_wa_result = await self.db.execute(
                    select(ClientModel.whatsapp_number).where(ClientModel.id == cart.client_id)
                )
                store_whatsapp = client_wa_result.scalar_one_or_none()

                payment_link = await self.create_paystack_payment_link(
                    reference=reference,
                    amount_naira=total_float,
                    phone=data.user_id,
                    subaccount_code=subaccount_code,
                    store_whatsapp=store_whatsapp,
                )
            except Exception as pay_err:
                logger.error(
                    "Paystack link creation failed for order %s: %s",
                    order.id, pay_err,
                )
                for item in cart.items:
                    try:
                        await self.inventory_service.adjust_stock(
                            merchant_id=data.merchant_id,
                            client_id=data.client_id,
                            product_id=str(item.product_id),
                            delta=item.quantity,
                        )
                    except Exception as inv_restore_err:
                        logger.error(
                            "Inventory restore failed for product %s after payment link failure: %s",
                            item.product_id, inv_restore_err,
                        )
                cart.checked_out = False
                cart.checked_out_at = None
                await self.db.flush()
                raise ValueError(
                    "Payment link could not be generated. Please try again in a moment."
                ) from pay_err

        elif data.payment_method == "cash":

            await self.payment_service.create_cash_payment(
                order_id=str(order.id),
                merchant_id=cart.merchant_id,
                client_id=cart.client_id,
                amount=Decimal(str(total_float)),
                customer_name=data.customer_name,
            )

        else:

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

        # ----------------------------
        # CLOSE CART (NON-CARD ONLY)
        # ----------------------------
        if data.payment_method != "card":
            cart.checked_out = True
            cart.checked_out_at = datetime.now(timezone.utc)

        # ----------------------------
        # PERSIST LAST ORDER ON PROFILE
        # ----------------------------
        if data.payment_method == "cash":
            try:
                from sqlalchemy import select as _sel
                from app.models.customer_profile import CustomerProfile as _CP
                _profile_res = await self.db.execute(
                    _sel(_CP).where(_CP.phone_number == data.user_id)
                )
                _profile = _profile_res.scalar_one_or_none()
                if _profile is not None:
                    _profile.set_last_order(
                        order_code=order.order_code,
                        total=total_float,
                        items=[
                            {"name": i.product.name, "qty": i.quantity}
                            for i in cart.items
                            if hasattr(i, "product") and i.product
                        ],
                        store=cart.client_id,
                        client_id=cart.client_id,
                    )
                    await self.db.flush()
            except Exception as _loe:
                logger.warning("last_order write failed (non-fatal): %s", _loe)

        # ----------------------------
        # RESPONSE
        # ----------------------------
        _estimated = getattr(data, "estimated_fulfillment_minutes", None)
        estimated_time_str = (
            f"{_estimated} minutes" if _estimated
            else "30–45 minutes"
        )
        _contact = getattr(data, "store_contact_number", None) or "Store"

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
            estimated_time=estimated_time_str,
            store_contact=_contact,
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
        delivery_type: Optional[str] = None,
        delivery_address: Optional[str] = None,
        delivery_contact_number: Optional[str] = None,
        delivery_fee: Optional[float] = None,
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
            customer_name=customer_name or user_id,
            pickup_location=None,
            delivery_address=delivery_address,
            delivery_type=delivery_type,
            delivery_contact_number=delivery_contact_number,
            delivery_fee=delivery_fee,
            store_contact_number=(
                getattr(tenant_context, "store_contact_number", None)
                if tenant_context else None
            ),
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
        store_whatsapp: Optional[str] = None,
    ) -> str:
        secret = os.getenv("PAYSTACK_SECRET_KEY")
        if not secret:
            raise ValueError("PAYSTACK_SECRET_KEY not configured")

        redirect_url = os.getenv("PAYSTACK_REDIRECT_URL", "")
        if redirect_url and reference:
            sep = "&" if "?" in redirect_url else "?"
            redirect_url = f"{redirect_url}{sep}ref={reference}"
            # Pass the store's WhatsApp number so the payment-success page can
            # deep-link the customer back to the right conversation.
            if store_whatsapp:
                redirect_url = f"{redirect_url}&wa={store_whatsapp}"

        amount_kobo = int(amount_naira * 100)
        email = f"{phone.replace('+', '')}@shopprhq.app"

        payload = {
            "reference": reference,
            "amount": amount_kobo,
            "currency": "NGN",
            "email": email,          # ← top-level, required by Paystack
            "callback_url": redirect_url,
            "customer": {
                "phone": phone,
                "email": email,
            },
            "channels": ["card", "bank", "ussd", "bank_transfer", "mobile_money"],
        }

        if subaccount_code:
            payload["subaccount"] = subaccount_code
            payload["bearer"] = "subaccount"
            logger.info(
                "Payment routed to Paystack subaccount %s (order: ₦%s)",
                subaccount_code, amount_naira,
            )
        else:
            logger.warning(
                "No Paystack subaccount for client — payment goes to platform account. "
                "Register one via POST /api/v1/subaccounts/{client_id}"
            )

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