# app/orchestrators/conversation_router.py

from typing import Dict, Any

from app.orchestrators.context import ConversationContext
from app.orchestrators.cart_orchestrator import CartOrchestrator
from app.orchestrators.checkout_orchestrator import CheckoutOrchestrator
from app.orchestrators.search_orchestrator import SearchOrchestrator
from app.orchestrators.payment_orchestrator import PaymentOrchestrator
from app.conversation.humanizer import Humanizer
import logging
logger = logging.getLogger(__name__)


class ConversationRouter:

    def __init__(self, context: ConversationContext):
        self.ctx = context

        self.cart     = CartOrchestrator(context)
        self.checkout = CheckoutOrchestrator(context)
        self.search   = SearchOrchestrator(context)
        self.payment  = PaymentOrchestrator(context)

        self.memory = context.memory

    # ==========================================================
    # MAIN ENTRYPOINT
    # ==========================================================

    async def route(
        self,
        *,
        intent: str,
        intent_payload: Dict[str, Any],
    ) -> str:

        current_mode = await self.memory.get_mode()

        # --------------------------------------------------
        # MODE FIRST — stateful flows take priority
        # --------------------------------------------------

        if current_mode == "selecting":
            return await self.search.handle_selection(self.ctx.user_text)

        # FIX: handle yes/no reply to "updating X to N - right?" confirmation
        if current_mode == "confirming_qty_update":
            return await self.cart.handle_qty_update_confirm(self.ctx.user_text)

        if current_mode == "confirming_qty":
            # UX-4: for catalogue-answerable intents fired while choosing a quantity,
            # answer the question but preserve the pending selection so the customer
            # can continue without having to search again.
            if intent in ("product_inquiry", "availability_check",
                          "price_check", "alternative_request"):
                # Answer the question, then re-append the quantity prompt
                _catalogue_answer = intent_payload.get("catalogue_answer")
                if _catalogue_answer:
                    pending = await self.memory.get_temp_data("pending_product")
                    if pending:
                        _name     = pending.get("name", "it")
                        _price    = pending.get("price", 0)
                        _nudge    = Humanizer.confirm_quantity_prompt(_name, _price)
                        return f"{_catalogue_answer}\n\n{_nudge}"
                    return _catalogue_answer
                # No pre-built answer — fall through to normal routing (clears mode)
                await self.memory.set_mode("idle")
                await self.memory.clear_temp()
            elif intent in ("view_cart", "checkout", "help",
                            "human_handoff", "store_info"):
                # These intents intentionally break the flow — clear mode
                await self.memory.set_mode("idle")
                await self.memory.clear_temp()
            else:
                return await self.search.handle_qty_confirmation(self.ctx.user_text)

        if current_mode in ("payment", "confirming_order"):
            # UX-8: confirming_order routes back to handle_payment_selection which
            # checks the mode internally and either confirms or cancels.
            return await self.checkout.handle_payment_selection(self.ctx.user_text)

        if current_mode == "choosing_delivery_type":
            return await self.checkout.handle_delivery_type_selection(self.ctx.user_text)

        if current_mode == "awaiting_delivery_address":
            return await self.checkout.handle_delivery_address(self.ctx.user_text)

        if current_mode == "awaiting_delivery_contact":
            return await self.checkout.handle_delivery_contact(self.ctx.user_text)

        # FIX: resume a pending card payment — send the existing Paystack link
        # instead of repeating the "you have an unpaid order" warning on every reply.
        if current_mode == "awaiting_payment_resume":
            return await self.checkout.handle_payment_resume(self.ctx.user_text)

        if current_mode == "confirming_new_order":
            # FLOW-4: customer saw the cart-clear warning — any affirmative confirms it
            _text_lower = self.ctx.user_text.strip().lower()
            _CONFIRM = {"yes", "yeah", "yep", "yup", "ok", "okay", "sure",
                        "confirm", "clear it", "clear", "proceed", "go ahead",
                        "oya", "yes please"}
            if _text_lower in _CONFIRM:
                return await self.cart.start_new_order()
            else:
                # Anything else — treat as abandoning the start-over
                await self.memory.set_mode("idle")
                return Humanizer._pick([
                    "No worries — your cart is still intact. Keep shopping or say *checkout* when you're ready.",
                    "Got it — nothing cleared. Your cart is still as you left it.",
                ])

        # --------------------------------------------------
        # INTENT ROUTING
        # --------------------------------------------------

        if intent == "product_search":
            return await self.search.search_products(
                intent_payload.get("search_query")
            )

        if intent == "add_to_cart":
            return await self.cart.add_to_cart(
                intent_payload.get("products", [])
            )

        if intent == "update_quantity":
            return await self.cart.update_quantity(
                intent_payload.get("quantity_updates", [])
            )

        if intent == "view_cart":
            return await self.cart.view_cart()

        if intent == "remove_from_cart":
            return await self.cart.remove_item(
                intent_payload.get("products", [])
            )

        if intent == "clear_cart":
            return await self.cart.clear_cart()

        if intent in ("new_order", "new", "reset"):
            return await self.cart.start_new_order()

        if intent == "repeat_order":
            return await self.cart.repeat_last_order()

        if intent == "cancel":
            return await self._handle_done()

        if intent == "checkout":
            return await self.checkout.initiate_checkout()

        if intent == "confirm_cash":
            return await self.payment.confirm_cash(
                intent_payload.get("order_code")
            )

        if intent == "order_status":
            return await self._handle_order_status(
                intent_payload.get("order_code", "").strip().upper()
            )

        if intent == "help":
            return Humanizer.help()

        if intent == "greeting":
            customer_name = await self.memory.get_customer_name()
            store_display = self.ctx.tenant.client_name or self.ctx.tenant.client_id
            # Always use persona_name — it returns assistant_name or a safe fallback.
            # Only pass it if assistant_name is actually configured; otherwise
            # the greeting reads more naturally without the bot's name.
            persona_name = (
                self.ctx.tenant.assistant_name
                if self.ctx.tenant.assistant_name
                else None
            )
            return Humanizer.greeting(store_display, customer_name, persona_name)

        if intent == "select_by_number":
            # FLOW-3: only honour a numeric selection when the customer is actually
            # in a selection flow.  Outside of selecting mode a bare digit is almost
            # certainly a stale number or misfire — show search_expired instead.
            if current_mode == "selecting":
                return await self.search.handle_selection(self.ctx.user_text)
            return Humanizer.search_expired()

        if intent == "confirm":
            # Generic "yes" in an ambiguous context — check if there's a pending product
            pending = await self.memory.get_temp_data("pending_product")
            if pending:
                return await self.search.handle_qty_confirmation(self.ctx.user_text)
            return Humanizer.social_acknowledgment(self.ctx.tenant.persona_style)

        if intent == "human_handoff":
            return self._handle_human_handoff()

        if intent in ("store_info", "info"):
            tenant  = self.ctx.tenant
            from app.conversation.store_hours import is_store_open
            is_open = is_store_open(tenant.opens_at, tenant.closes_at, tenant.store_timezone)
            return Humanizer.store_hours_info(
                opens_at=tenant.opens_at,
                closes_at=tenant.closes_at,
                is_open=is_open,
                store_name=tenant.client_name,
            )

        return Humanizer.fallback(self.ctx.tenant.persona_style)

    # ==========================================================
    # HUMAN HANDOFF
    # ==========================================================

    def _handle_human_handoff(self) -> str:
        """
        Customer wants to speak to a real person.
        We direct them to the store operator via WhatsApp.
        """
        tenant     = self.ctx.tenant
        store_name = tenant.client_name or "the store"
        # If operator number is configured, give them a direct contact.
        if tenant.operator_notify_phone:
            op_number = tenant.operator_notify_phone.lstrip("+")
            return Humanizer.human_handoff_with_number(store_name, op_number)
        return Humanizer.human_handoff_no_number(store_name)

    # ==========================================================
    # DONE / CANCEL
    # ==========================================================

    async def _handle_done(self) -> str:
        from app.services.cart_service import CartService
        cart_service = CartService(self.ctx.db)
        summary = await cart_service.get_cart_summary(
            merchant_id=str(self.ctx.tenant.merchant_id),
            client_id=str(self.ctx.tenant.client_id),
            user_id=self.ctx.user_phone,
        )
        if summary.get("has_items"):
            total_str = Humanizer._format_currency(summary["total"])
            return Humanizer._pick([
                f"No problem! Whenever you're ready, just say *checkout* to pay.\nYour cart total is *{total_str}*.",
                f"Got it! Say *checkout* when you're ready to pay. Total so far: *{total_str}*.",
                f"Sure thing. Your cart total is *{total_str}* — just say *checkout* whenever you like.",
            ])
        return Humanizer._pick([
            "No worries! Just let me know when you'd like to order something.",
            "All good — I'm here whenever you need me.",
        ])

    # ==========================================================
    # ORDER STATUS
    # ==========================================================

    async def _handle_order_status(self, order_code: str) -> str:

        from app.services.order_query_service import OrderQueryService
        from sqlalchemy import select, desc

        service = OrderQueryService(self.ctx.db)

        if not order_code:
            # FLOW-5: no code supplied — look up the customer's most recent order
            # for this store by phone number so they don't need to remember it.
            try:
                from app.models.order import Order
                result = await self.ctx.db.execute(
                    select(Order)
                    .where(
                        Order.merchant_id == str(self.ctx.tenant.merchant_id),
                        Order.client_id   == str(self.ctx.tenant.client_id),
                        Order.user_id     == self.ctx.user_phone.lstrip("+").strip(),
                    )
                    .order_by(desc(Order.created_at))
                    .limit(1)
                )
                latest = result.scalars().first()
                if latest:
                    order_code = latest.order_code
                else:
                    return Humanizer.order_status_prompt()
            except Exception as _e:
                logger.warning("Latest-order lookup failed: %s", _e)
                return Humanizer.order_status_prompt()

        order   = await service.get_order_by_code(
            order_code=order_code,
            merchant_id=str(self.ctx.tenant.merchant_id),
        )

        if not order:
            return Humanizer.order_status_not_found(order_code)

        status_map = {
            "pending_payment":  "Waiting for payment",
            "awaiting_pickup":  "Ready for pickup — head to the store whenever you're ready",
            "out_for_delivery": "🚴 On the way to you!",
            "fulfilled":        "Completed ✅",
            "cancelled":        "Cancelled",
            "paid":             "Paid — being prepared",
            "created":          "Just placed",
        }

        status_label = status_map.get(order["status"].lower(), order["status"])
        total_str    = Humanizer._format_currency(order["total_amount"])

        lines = [
            f"*Order {order_code}*\n",
            f"Status: {status_label}",
            f"Total: {total_str}",
            f"Payment: {order['payment_method'].title()}",
        ]
        if order.get("customer_name"):
            lines.append(f"Name: {order['customer_name']}")

        return "\n".join(lines)
