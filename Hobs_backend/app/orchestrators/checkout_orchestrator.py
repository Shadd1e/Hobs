# app/orchestrators/checkout_orchestrator.py

import logging
from typing import Optional

from sqlalchemy.exc import IntegrityError

from app.conversation.humanizer import Humanizer
from app.orchestrators.context import ConversationContext
from app.services.operator_notification_service import OperatorNotificationService
from app.core.redis_client import SESSION_TTL

logger = logging.getLogger(__name__)

_KEY_DELIVERY_TYPE    = "checkout_delivery_type"
_KEY_DELIVERY_ADDRESS = "checkout_delivery_address"

_CHECKOUT_SESSION_TTL = SESSION_TTL * 2  # 4 hours


class CheckoutOrchestrator:
    """
    Manages the checkout conversation flow.

    Steps (when delivery is enabled for this store):
      1. initiate_checkout   → asks pickup vs delivery
      2. handle_delivery_type_selection → captures "1"/"2"
         a. If pickup  → ask payment method
         b. If delivery → ask for address
      3. handle_delivery_address   → captures free-text address
      4. handle_delivery_contact   → captures contact number or "same"
      5. handle_payment_selection  → captures "1" (cash) or "2" (card)

    When delivery is disabled:
      1. initiate_checkout  → asks payment method directly
      2. handle_payment_selection

    RULES:
    - No transaction ownership
    - No DB commits
    - Delegates to domain services
    """

    def __init__(self, context: ConversationContext):
        self.ctx              = context
        self.checkout_service = context.checkout_service
        self.cart_service     = context.cart_service
        self.memory           = context.memory
        self.tenant           = context.tenant

        self.merchant_id = str(context.tenant.merchant_id)
        self.client_id   = str(context.tenant.client_id)
        self.user_id     = context.user_phone

    # ----------------------------------------------------------
    # INTERNAL: extend session TTL for the checkout window
    # ----------------------------------------------------------
    async def _extend_checkout_session(self) -> None:
        try:
            from app.core.redis_client import redis_service, Keys
            client = await redis_service.get_client()
            key = Keys.session_flow(str(self.tenant.client_id), self.user_id)
            await client.expire(key, _CHECKOUT_SESSION_TTL)
        except Exception as e:
            logger.warning("_extend_checkout_session failed (non-fatal): %s", e)

    # ==========================================================
    # STEP 1 — INITIATE CHECKOUT
    # ==========================================================

    async def initiate_checkout(self) -> str:

        summary = await self.cart_service.get_cart_summary(
            merchant_id=self.merchant_id,
            client_id=self.client_id,
            user_id=self.user_id,
        )

        if not summary["has_items"]:
            return Humanizer.empty_cart_checkout(self.tenant.persona_style)

        # ── Check for a stale pending card order before proceeding ────────────
        try:
            from sqlalchemy import select as _sa_select
            from app.models.order import Order, OrderStatus

            _res = await self.ctx.db.execute(
                _sa_select(Order).where(
                    Order.merchant_id == self.merchant_id,
                    Order.client_id   == self.client_id,
                    Order.user_id     == self.user_id,
                    Order.status      == OrderStatus.PENDING_PAYMENT,
                )
            )
            stale_order = _res.scalar_one_or_none()

            if stale_order:
                await self.memory.set("pending_card_order_id", str(stale_order.id))
                await self.memory.set_mode("awaiting_payment_resume")
                return (
                    f"You have an unpaid card order (*{stale_order.order_code}*) still open. "
                    f"Complete the payment, or send *new* to cancel it and start fresh."
                )
        except Exception:
            pass

        if self.tenant.delivery_ready:
            await self._extend_checkout_session()
            await self.memory.set_mode("choosing_delivery_type")
            return Humanizer.checkout_delivery_type_prompt(
                total=summary["total"],
                delivery_fee=float(self.tenant.delivery_fee),
                delivery_area=self.tenant.delivery_area,
            )

        # No delivery → go straight to payment method
        await self._extend_checkout_session()
        await self.memory.set_mode("payment")
        return Humanizer.checkout_prompt(summary["total"], self.tenant.persona_style)

    # ==========================================================
    # STEP 2 — DELIVERY TYPE SELECTION
    # ==========================================================

    async def handle_delivery_type_selection(self, user_input: str) -> str:
        _raw = user_input.strip().lower()

        _PICKUP_WORDS = {
            "1", "pickup", "pick up", "pick-up", "collect", "collection",
            "i'll collect", "ill collect", "i will collect",
            "i'll pick it up", "ill pick it up", "picking it up",
            "store pickup", "self collect", "come get it",
        }
        _DELIVERY_WORDS = {
            "2", "delivery", "deliver", "deliver it", "deliver to me",
            "bring it", "bring to me", "home delivery", "door delivery",
            "send it", "send to me", "i want delivery", "deliver it to me",
            "drop it off", "drop off",
        }

        if _raw in _PICKUP_WORDS:
            choice = "1"
        elif _raw in _DELIVERY_WORDS:
            choice = "2"
        else:
            return Humanizer.checkout_delivery_type_retry()

        if choice == "1":
            await self.memory.delete(_KEY_DELIVERY_TYPE)
            await self.memory.delete(_KEY_DELIVERY_ADDRESS)
            await self.memory.set(_KEY_DELIVERY_TYPE, "pickup")
            await self.memory.set_mode("payment")
            await self._extend_checkout_session()
            summary = await self.cart_service.get_cart_summary(
                merchant_id=self.merchant_id,
                client_id=self.client_id,
                user_id=self.user_id,
            )
            return Humanizer.checkout_prompt(summary["total"], self.tenant.persona_style)

        await self.memory.set(_KEY_DELIVERY_TYPE, "delivery")
        await self.memory.set_mode("awaiting_delivery_address")
        await self._extend_checkout_session()
        return Humanizer.ask_delivery_address(self.tenant.delivery_area)

    # ==========================================================
    # STEP 3 — DELIVERY ADDRESS
    # ==========================================================

    async def handle_delivery_address(self, user_input: str) -> str:
        import re as _re
        address = user_input.strip()[:500]

        _has_digit = bool(_re.search(r'\d', address))
        _word_tokens = [w for w in _re.split(r'\W+', address.lower()) if len(w) >= 2]
        _has_enough_words = len(set(_word_tokens)) >= 2

        if not _has_digit or not _has_enough_words:
            return (
                "Please include your house/plot number and street name so we can find you. "
                "For example: *12 Adeola Street, Lekki Phase 1*"
            )

        await self.memory.set(_KEY_DELIVERY_ADDRESS, address)
        await self.memory.set_mode("awaiting_delivery_contact")
        await self._extend_checkout_session()

        delivery_area = self.tenant.delivery_area
        if delivery_area:
            area_lower    = delivery_area.lower()
            address_lower = address.lower()
            area_words    = [w for w in area_lower.split() if len(w) > 2]
            looks_local   = area_lower in address_lower or any(
                w in address_lower for w in area_words
            )
            if not looks_local:
                _warning = (
                    f"Just a heads-up — we currently only deliver within {delivery_area}. "
                    f"If your address is outside {delivery_area}, your order may not be fulfilled. "
                    f"If you're within the area, no worries — just continue.\n\n"
                )
                return _warning + Humanizer.ask_delivery_contact()

        return Humanizer.ask_delivery_contact()

    # ==========================================================
    # STEP 4 — DELIVERY CONTACT NUMBER
    # ==========================================================

    async def handle_delivery_contact(self, user_input: str) -> str:
        raw = user_input.strip().lower()

        if raw in ("same", "same number", "this number", "my number"):
            contact_number = self.user_id
        else:
            import re
            cleaned = re.sub(r"[\s\-()]", "", raw)
            if not re.match(r"^\+?\d{7,15}$", cleaned):
                return (
                    "That doesn't look like a phone number. "
                    "Please type a valid number, or reply *same* to use this WhatsApp number."
                )
            contact_number = cleaned

        await self.memory.set("checkout_delivery_contact", contact_number)
        await self.memory.set_mode("payment")
        await self._extend_checkout_session()

        summary        = await self.cart_service.get_cart_summary(
            merchant_id=self.merchant_id,
            client_id=self.client_id,
            user_id=self.user_id,
        )
        address        = await self.memory.get(_KEY_DELIVERY_ADDRESS, "")
        delivery_fee   = float(self.tenant.delivery_fee or 0)
        total_with_fee = summary["total"] + delivery_fee

        return Humanizer.delivery_details_confirmed(
            address=address,
            total_with_fee=total_with_fee,
        )

    # ==========================================================
    # STEP 5 — PAYMENT METHOD SELECTION
    # ==========================================================

    async def handle_payment_selection(self, user_input: str) -> str:

        _raw  = user_input.strip().lower()
        _CASH = {"1", "cash", "pay cash", "cash payment", "pay at store",
                 "pickup", "pick up", "i'll pay cash", "cash on pickup"}
        _CARD = {"2", "card", "pay card", "online", "pay online",
                 "card payment", "transfer", "pay by card", "online payment"}

        current_mode = await self.memory.get_mode()
        if current_mode == "confirming_order":
            _CONFIRM = {"yes", "yeah", "yep", "yup", "ok", "okay", "sure",
                        "confirm", "place order", "proceed", "go ahead",
                        "oya", "do it", "yes please"}
            if _raw not in _CONFIRM:
                await self.memory.set_mode("payment")
                await self.memory.delete("pending_payment_method")
                return Humanizer._pick([
                    "No problem — order cancelled. Say *checkout* whenever you're ready to try again.",
                    "Got it — nothing placed. Your cart is still intact. Say *checkout* to try again.",
                ])
            _raw = await self.memory.get("pending_payment_method", _raw)

        if _raw in _CASH:
            payment_method = "cash"
        elif _raw in _CARD:
            payment_method = "card"
        else:
            return Humanizer.checkout_prompt_retry()

        delivery_type    = await self.memory.get(_KEY_DELIVERY_TYPE)
        delivery_address = await self.memory.get(_KEY_DELIVERY_ADDRESS)
        delivery_contact = await self.memory.get("checkout_delivery_contact")
        delivery_fee     = (
            float(self.tenant.delivery_fee)
            if delivery_type == "delivery" and self.tenant.delivery_fee
            else None
        )

        pre_checkout_summary = await self.cart_service.get_cart_summary(
            merchant_id=self.merchant_id,
            client_id=self.client_id,
            user_id=self.user_id,
        )
        items_text = "\n".join(
            f"  • {i['quantity']}x {i['product_name']}"
            for i in pre_checkout_summary.get("items", [])
        ) or "  (items unavailable)"

        if current_mode != "confirming_order":
            total_val        = pre_checkout_summary.get("total", 0)
            delivery_fee_val = float(self.tenant.delivery_fee or 0) if delivery_type == "delivery" else 0
            grand_total      = total_val + delivery_fee_val
            total_str        = Humanizer._format_currency(grand_total)
            pay_label        = "Cash on delivery" if payment_method == "cash" else "Card (online payment)"
            delivery_line    = (
                f"\nDelivery: {Humanizer._format_currency(delivery_fee_val)}"
                if delivery_fee_val else ""
            )
            confirmation_msg = (
                f"📋 *Order Summary*\n\n"
                f"{items_text}\n"
                f"{delivery_line}"
                f"\n*Total: {total_str}*"
                f"\nPayment: {pay_label}"
                f"\n\nReply *yes* to confirm and place your order, or *no* to cancel."
            )
            await self.memory.set("pending_payment_method", _raw)
            await self.memory.set_mode("confirming_order")
            await self._extend_checkout_session()
            return confirmation_msg

        if payment_method == "card":
            try:
                from app.services.whatsapp_sender import send_whatsapp_message
                await send_whatsapp_message(
                    to_number=self.user_id,
                    message="Generating your payment link — just a moment! ⏳",
                    phone_number_id=getattr(self.ctx.tenant, "phone_number_id", ""),
                )
            except Exception as _hold_err:
                logger.debug("Holding message failed (non-fatal): %s", _hold_err)

        _checkout_err = None
        result = None
        try:
            customer_name = await self.memory.get_customer_name()

            result = await self.checkout_service.checkout_from_whatsapp(
                merchant_id=self.merchant_id,
                client_id=self.client_id,
                user_id=self.user_id,
                payment_method=payment_method,
                customer_name=customer_name,
                delivery_type=delivery_type,
                delivery_address=delivery_address,
                delivery_contact_number=delivery_contact,
                delivery_fee=delivery_fee,
                tenant_context=self.tenant,
            )

        except (IntegrityError, ValueError, Exception) as _e:
            _checkout_err = _e

        finally:
            try:
                await self.memory.set_mode("idle")
                await self.memory.delete(_KEY_DELIVERY_TYPE)
                await self.memory.delete(_KEY_DELIVERY_ADDRESS)
                await self.memory.delete("checkout_delivery_contact")
                await self.memory.clear_choices()
            except Exception as mem_err:
                logger.error("Memory cleanup after checkout failed: %s", mem_err)

        if _checkout_err is not None:
            if isinstance(_checkout_err, IntegrityError):
                logger.warning("Duplicate order attempt blocked for user %s", self.user_id)
                return Humanizer.checkout_already_active(self.tenant.persona_style)
            if isinstance(_checkout_err, ValueError):
                err = str(_checkout_err)
                if "already checked out" in err or "already has" in err.lower():
                    return Humanizer.checkout_already_active(self.tenant.persona_style)
                logger.error("Checkout value error: %s", err)
                return Humanizer.checkout_failed(self.tenant.persona_style)
            logger.exception("Checkout failed", exc_info=_checkout_err)
            return Humanizer.checkout_failed(self.tenant.persona_style)

        logger.info(
            "[ORDER_PLACED] merchant_id=%s order_code=%s payment_method=%s "
            "total=%.2f client_id=%s customer=%s",
            self.merchant_id, result.order_code, payment_method,
            result.total_amount, self.client_id, self.user_id,
        )

        try:
            op_phone        = getattr(self.ctx.tenant, "operator_notify_phone", None)
            phone_number_id = getattr(self.ctx.tenant, "phone_number_id", None)
            store_name      = self.ctx.tenant.client_name or self.ctx.tenant.client_id

            if op_phone and phone_number_id:
                notifier = OperatorNotificationService(
                    operator_phone=op_phone,
                    phone_number_id=phone_number_id,
                    store_name=store_name,
                )
                await notifier.new_order_ping(
                    order_code=result.order_code,
                    payment_method=payment_method,
                    total=result.total_amount,
                )
        except Exception as op_err:
            logger.error("Operator new-order ping failed: %s", op_err)

        if payment_method == "cash":
            if delivery_type == "delivery":
                instructions = Humanizer.checkout_instructions_cash_delivery(result.order_code)
            else:
                instructions = Humanizer.checkout_instructions_cash(result.order_code)

            return Humanizer.checkout_success(
                order_code=result.order_code,
                total=result.total_amount,
                instructions=instructions, style=self.tenant.persona_style,
            )

        if result.payment_link:
            return Humanizer.checkout_pending(result.payment_link, self.tenant.persona_style)

        return Humanizer.checkout_success(
            order_code=result.order_code,
            total=result.total_amount,
            instructions="Your payment is being processed.", style=self.tenant.persona_style,
        )

    # ==========================================================
    # RESUME PENDING CARD PAYMENT
    # ==========================================================

    async def handle_payment_resume(self, user_input: str) -> str:
        _raw = user_input.strip().lower()

        _COMPLETE_WORDS = {
            "complete", "complete the payment", "complete payment",
            "pay", "pay now", "make payment", "i want to pay",
            "i want to complete the payment", "finish payment",
            "yes", "ok", "okay", "sure", "proceed", "go ahead",
            "send link", "resend link", "payment link",
        }

        if _raw not in _COMPLETE_WORDS:
            # They said something else — drop out of this mode and re-evaluate
            await self.memory.set_mode("idle")
            await self.memory.delete("pending_card_order_id")
            return await self.initiate_checkout()

        order_id = await self.memory.get("pending_card_order_id")
        if not order_id:
            await self.memory.set_mode("idle")
            return await self.initiate_checkout()

        try:
            from sqlalchemy import select as _sa_select
            from app.models.payment import Payment, PaymentStatus
            from app.models.order import Order
            from app.services.flutterwave_subaccount_service import FlutterwaveSubaccountService

            # Fetch the order
            _order_res = await self.ctx.db.execute(
                _sa_select(Order).where(Order.id == order_id)
            )
            order = _order_res.scalar_one_or_none()
            if not order:
                await self.memory.set_mode("idle")
                await self.memory.delete("pending_card_order_id")
                return "Couldn't find that order. Send *new* to start fresh."

            # Fetch the pending payment to get the reference
            _pay_res = await self.ctx.db.execute(
                _sa_select(Payment).where(
                    Payment.order_id == order_id,
                    Payment.status   == PaymentStatus.PENDING,
                ).limit(1)
            )
            payment = _pay_res.scalar_one_or_none()
            if not payment:
                await self.memory.set_mode("idle")
                await self.memory.delete("pending_card_order_id")
                return (
                    f"Couldn't find an active payment for order *{order.order_code}*. "
                    f"Send *new* to cancel and start fresh."
                )

            # Regenerate the Flutterwave link using the existing reference
            subaccount_service = FlutterwaveSubaccountService(self.ctx.db)
            subaccount_id = await subaccount_service.get_subaccount_id(
                client_id=self.client_id,
                merchant_id=self.merchant_id,
            )

            payment_link = await self.checkout_service.create_flutterwave_payment_link(
                reference=payment.external_reference,
                amount_naira=float(order.total_amount),
                phone=self.user_id,
                subaccount_id=subaccount_id,
            )

            await self.memory.set_mode("idle")
            await self.memory.delete("pending_card_order_id")
            await self._extend_checkout_session()

            return Humanizer.checkout_pending(payment_link, self.tenant.persona_style)

        except Exception as e:
            logger.error("Payment resume failed for order %s: %s", order_id, e)
            await self.memory.set_mode("idle")
            await self.memory.delete("pending_card_order_id")
            return (
                "Sorry, I couldn't regenerate your payment link. "
                "Send *new* to cancel that order and start fresh."
            )