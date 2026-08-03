# app/orchestrators/whatsapp_handler.py

import re
import uuid
import logging
from typing import Dict, Any

from app.db.session import AsyncSessionLocal
from app.core.redis_client import acquire_user_lock, release_user_lock, get_history
from app.core.config import settings  # FIX: was `Settings` (the class) — must be `settings` (the instance)
from app.services.cart_service import CartService
from app.services.checkout_service import CheckoutService
from app.services.fuzzy_match import FuzzyMatcher
from app.services.product_catalogue_service import ProductCatalogueService
from app.conversation.memory import ConversationMemory
from app.services.deepseek_service import (
    classify_intent,
    _is_category_browse,
    _is_cart_query,
    _is_human_handoff,
    _extract_number_word,
)
from app.services.whatsapp_sender import send_whatsapp_message, send_typing_indicator
from app.conversation.store_hours import is_store_open

from app.orchestrators.context import ConversationContext
from app.orchestrators.conversation_router import ConversationRouter
from app.conversation.humanizer import Humanizer

logger = logging.getLogger(__name__)

_STATUS_PREFIXES   = ("status ", "order ", "track ")
_catalogue_service = ProductCatalogueService()

# Social acknowledgments — never treated as product searches.
# Matching is done on both raw and punctuation-stripped text.
_SOCIAL_WORDS = frozenset({
    "okay", "ok", "k", "kk", "okay thanks", "ok thanks",
    "thank you", "thanks", "thx", "ty",
    "noted", "got it", "understood", "alright", "cool", "nice",
    "great", "perfect", "good", "fine", "no problem", "np",
    "lol", "haha", "😊", "👍", "😄", "👌",
    "oh okay", "oh ok", "oh alright", "oh nice",
    "no", "nah", "nope", "not really", "no thanks", "no thank you",
    "never mind", "nevermind", "thats all", "that's all",
    "im good", "i'm good", "im fine", "i'm fine",
    "nothing else", "nothing",
    "okay thank you", "ok thank you",
    "thanks!", "bye", "goodbye", "later", "see you", "cheers",
    "oya", "na true", "correct", "e good",
})

# Store hours fast-path phrases
_HOURS_PHRASES = (
    "when do you close", "when do you open", "what time do you close",
    "what time do you open", "are you open", "are you closed",
    "opening time", "closing time", "store hours", "business hours",
    "what are your hours", "when are you open", "what time are you",
)


def _phones_match(phone_a: str, phone_b: str) -> bool:
    a = re.sub(r"\D", "", phone_a or "")
    b = re.sub(r"\D", "", phone_b or "")
    if not a or not b:
        return False
    return a[-10:] == b[-10:]


def _normalise(text: str) -> str:
    """Lowercase and strip punctuation for social-word matching."""
    return re.sub(r"[^\w\s]", "", text.lower()).strip()


def _format_cart_summary(summary: dict) -> str | None:
    """
    Convert cart_svc.get_cart_summary() dict into a compact string
    suitable for injection into the DeepSeek system prompt.
    Returns None when the cart is empty so the prompt section is omitted entirely.
    """
    if not summary or not summary.get("has_items"):
        return None
    lines = [
        f"{i['quantity']}x {i['product_name']} — ₦{i['price']:,.0f} each (₦{i['subtotal']:,.0f})"
        for i in summary.get("items", [])
    ]
    total = summary.get("total", 0.0)
    lines.append(f"Total: ₦{total:,.0f}")
    return "\n".join(lines)


# ======================================================
# OPERATOR COMMAND HANDLER
# ======================================================

async def _handle_operator_command(
    *,
    user_text: str,
    tenant,
    phone_number_id: str,
) -> str:
    text = user_text.strip()
    tl   = text.lower()
    mid  = str(tenant.merchant_id)
    cid  = str(tenant.client_id)

    if tl in ("help", "hi", "hello", "commands"):
        return (
            "👋 *Store Operator Commands*\n\n"
            "*ORDERCODE* — view full order details (e.g. _X7K4M2PQ_)\n"
            "*orders* — view all pending orders\n"
            "*confirm ORDERCODE* — mark a cash order as fulfilled\n"
            "*help* — show this message"
        )

    if tl == "orders":
        from sqlalchemy import select
        from app.models.order import Order, OrderStatus
        from datetime import datetime, timezone

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Order).where(
                    Order.merchant_id == mid,
                    Order.client_id   == cid,
                    Order.status.in_([
                        OrderStatus.AWAITING_PICKUP,
                        OrderStatus.OUT_FOR_DELIVERY,
                    ]),
                )
            )
            orders = result.scalars().all()

        if not orders:
            return "No pending orders right now. Check back later!"

        lines = [f"📦 *Pending Orders ({len(orders)})*\n"]
        for o in orders[:10]:
            type_tag = "🛵 Delivery" if o.is_delivery_order else "📦 Pickup"
            lines.append(
                f"• *{o.order_code}* — ₦{float(o.total_amount):,.0f} "
                f"({type_tag}, {o.payment_method})"
            )
        return "\n".join(lines)

    if tl.startswith("confirm "):
        order_code = text[8:].strip().upper()
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from app.models.order import Order, OrderStatus
        from app.models.cart import Cart, CartItem
        from app.models.client_whatsapp_credential import ClientWhatsAppCredential
        from datetime import datetime, timezone

        _receipt_info = None

        async with AsyncSessionLocal() as db:
            async with db.begin():
                result = await db.execute(
                    select(Order).where(
                        Order.order_code  == order_code,
                        Order.merchant_id == mid,
                        Order.client_id   == cid,
                    ).with_for_update()
                )
                order = result.scalar_one_or_none()

                if not order:
                    return f"No order found with code *{order_code}*."
                if order.payment_method != "cash":
                    return f"Order *{order_code}* is a card order — it confirms automatically."
                if order.status == OrderStatus.FULFILLED:
                    return f"Order *{order_code}* is already fulfilled. ✅"
                if order.status not in (OrderStatus.AWAITING_PICKUP, OrderStatus.OUT_FOR_DELIVERY):
                    return f"Order *{order_code}* can't be confirmed right now (status: {order.status.value})."

                order.status       = OrderStatus.FULFILLED
                order.confirmed_at = datetime.now(timezone.utc)

                try:
                    cred_result = await db.execute(
                        select(ClientWhatsAppCredential).where(
                            ClientWhatsAppCredential.client_id == order.client_id,
                            ClientWhatsAppCredential.active.is_(True),
                        )
                    )
                    cred = cred_result.scalar_one_or_none()
                    if cred and order.user_id:
                        cart_result = await db.execute(
                            select(Cart).where(Cart.id == order.cart_id)
                            .options(selectinload(Cart.items).selectinload(CartItem.product))
                        )
                        cart  = cart_result.scalar_one_or_none()
                        items = cart.items if cart else []
                        nl    = "\n"
                        items_lines = nl.join(
                            f"{i.quantity}x {getattr(i.product, 'name', '?')} — "
                            f"₦{float(i.price_at_add) * i.quantity:,.2f}"
                            for i in items
                        ) or "(items unavailable)"
                        _receipt_info = {
                            "to_number":       order.user_id,
                            "phone_number_id": cred.phone_number_id,
                            "order_code":      order.order_code,
                            "total":           float(order.total_amount),
                            "items_lines":     items_lines,
                        }
                except Exception as gather_err:
                    logger.error("Operator confirm — receipt gather failed: %s", gather_err)

        if _receipt_info:
            try:
                receipt_msg = Humanizer.cash_payment_receipt(
                    order_code=_receipt_info["order_code"],
                    total=_receipt_info["total"],
                    items_lines=_receipt_info["items_lines"],
                    store_name=tenant.client_name or None,
                )
                await send_whatsapp_message(
                    to_number=_receipt_info["to_number"],
                    message=receipt_msg,
                    phone_number_id=_receipt_info["phone_number_id"],
                )
            except Exception as receipt_err:
                logger.error("Operator confirm — receipt send failed: %s", receipt_err)

        return f"✅ Order *{order_code}* confirmed and receipt sent to customer."

    if tl.startswith("status "):
        order_code = text[7:].strip().upper()
        from sqlalchemy import select
        from app.models.order import Order

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Order).where(
                    Order.order_code  == order_code,
                    Order.merchant_id == mid,
                )
            )
            order = result.scalar_one_or_none()

        if not order:
            return f"No order found with code *{order_code}*."

        type_label = "Delivery 🛵" if order.is_delivery_order else "Pickup 📦"
        lines = [
            f"*Order {order_code}*",
            f"Status: *{order.status.value}*",
            f"Type: {type_label}",
            f"Total: ₦{float(order.total_amount):,.0f}",
            f"Payment: {order.payment_method}",
        ]
        if order.is_delivery_order and order.delivery_address:
            lines.append(f"Address: _{order.delivery_address}_")
        return "\n".join(lines)

    # Bare order code lookup
    _candidate = text.upper().strip()
    if len(_candidate) >= 6 and _candidate.isalnum():
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from app.models.order import Order

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Order).where(
                    Order.order_code  == _candidate,
                    Order.merchant_id == mid,
                    Order.client_id   == cid,
                ).options(selectinload(Order.cart))
            )
            order = result.scalar_one_or_none()

        if order:
            type_label = "Delivery 🛵" if order.is_delivery_order else "Pickup 📦"
            lines = [
                f"*Order {_candidate}*",
                f"Status: *{order.status.value}*",
                f"Type: {type_label}",
                f"Payment: {order.payment_method}",
                f"Total: ₦{float(order.total_amount):,.0f}",
                f"Customer: +{str(order.user_id).lstrip('+')} " if order.user_id else "",
            ]
            if order.customer_name:
                lines.append(f"Name: {order.customer_name}")
            if order.is_delivery_order and order.delivery_address:
                lines.append(f"Address: _{order.delivery_address}_")
            if order.is_delivery_order and order.delivery_contact_number:
                lines.append(f"Contact: +{order.delivery_contact_number.lstrip('+')}")
            lines = [l for l in lines if l]
            return "\n".join(lines)

    return "I didn't recognise that command. Send *help* to see available commands."


# ======================================================
# MAIN HANDLER
# ======================================================

async def handle_whatsapp_message(
    *,
    tenant,
    message_data: Dict[str, Any],
    phone_number_id: str,
) -> None:

    merchant_id = str(tenant.merchant_id)
    client_id   = str(tenant.client_id)
    user_phone  = message_data.get("from", "").replace("+", "").strip()
    user_text   = message_data.get("text", {}).get("body", "").strip()
    request_id  = str(uuid.uuid4())
    answer      = None

    if not user_text:
        return

    # ── Verification grace period: messaging suspension ─────────────────────
    # Set by an admin (POST /admin/whatsapp-setup/merchants/{id}/suspend-messaging)
    # when a merchant still hasn't submitted CAC/BVN/NIN well past the 7-day
    # grace period. Everything else about the account keeps working; this
    # only stops the bot from replying. We still send the customer one
    # graceful message rather than going silent, and skip the AI pipeline
    # entirely so a suspended merchant doesn't burn LLM calls either.
    try:
        from sqlalchemy import select as _select
        from app.models.merchant import Merchant

        async with AsyncSessionLocal() as _db:
            _res = await _db.execute(
                _select(Merchant.messaging_suspended_at).where(Merchant.id == merchant_id)
            )
            _suspended_at = _res.scalar_one_or_none()

        if _suspended_at is not None:
            await send_whatsapp_message(
                to_number=user_phone,
                message=(
                    "Thanks for reaching out! This store is temporarily unable "
                    "to receive WhatsApp orders while the owner completes a "
                    "quick verification step. Please try again shortly."
                ),
                phone_number_id=phone_number_id,
            )
            return
    except Exception:
        # Never let the suspension check itself take the bot down.
        logger.exception("Messaging-suspension check failed for merchant %s — allowing message through", merchant_id)

    # UX-1: fire typing indicator immediately so the customer sees activity
    # during the 2-5 seconds of lock acquisition + LLM classification.
    try:
        import asyncio as _asyncio
        _asyncio.create_task(
            send_typing_indicator(to_number=user_phone, phone_number_id=phone_number_id)
        )
    except Exception:
        pass  # non-fatal — never block message processing for a typing indicator

    # ── Operator command shortcut ─────────────────────────────────────────────
    if (
        tenant.operator_notify_phone
        and _phones_match(user_phone, tenant.operator_notify_phone)
    ):
        answer = await _handle_operator_command(
            user_text=user_text,
            tenant=tenant,
            phone_number_id=phone_number_id,
        )
        if answer:
            await send_whatsapp_message(
                to_number=user_phone,
                message=answer,
                phone_number_id=phone_number_id,
            )
        return

    # ── Per-user lock ─────────────────────────────────────────────────────────
    lock_acquired = await acquire_user_lock(
        merchant_id=merchant_id,
        user_phone=user_phone,
        lock_value=request_id,
    )
    if not lock_acquired:
        logger.info("Lock busy for %s — dropping duplicate", user_phone)
        return

    try:
        async with AsyncSessionLocal() as db:
            async with db.begin():

                memory   = await ConversationMemory.load(client_id, user_phone)
                cart_svc = CartService(db)
                matcher  = FuzzyMatcher(db)

                catalogue_ctx = await _catalogue_service.get_catalogue_context(
                    db=db,
                    merchant_id=merchant_id,
                    client_id=client_id,
                )

                ctx = ConversationContext(
                    tenant=tenant,
                    db=db,
                    user_phone=user_phone,
                    user_text=user_text,
                    phone_number_id=phone_number_id,
                    memory=memory,
                    cart_service=cart_svc,
                    checkout_service=CheckoutService(db),
                    matcher=matcher,
                )

                router = ConversationRouter(ctx)

                text_lower = user_text.lower().strip()
                text_norm  = _normalise(user_text)
                # Also strip trailing punctuation for social matching
                text_rtrim = text_lower.rstrip(".,!?").strip()

                intent:         str | None        = None
                intent_payload: Dict[str, Any]    = {}

                # ── Store hours notice ────────────────────────────────────────
                # Show the closed notice once per session — not on every reply.
                # Prepending it to every turn is noisy and reads badly mid-checkout.
                _closed_notice = ""
                if tenant.opens_at and tenant.closes_at:
                    _store_open_now = is_store_open(tenant.opens_at, tenant.closes_at, tenant.store_timezone)
                    if not _store_open_now:
                        _already_shown = await memory.get("closed_notice_shown")
                        if not _already_shown:
                            _closed_notice = Humanizer.store_closed_notice(
                                opens_at=tenant.opens_at,
                                closes_at=tenant.closes_at,
                                store_name=tenant.client_name,
                            )
                            await memory.set("closed_notice_shown", True)
                    else:
                        # Store has re-opened — clear the flag so next closure shows fresh notice
                        await memory.delete("closed_notice_shown")

                # ── Social message fast-path ──────────────────────────────────
                # FIX: added awaiting_payment_resume so social words like "ok",
                # "sure", "yes" are NOT swallowed by the social fast-path when the
                # customer is trying to complete a pending card payment. Those words
                # are valid affirmatives in handle_payment_resume and must reach the
                # mode router in conversation_router.py.
                _stateful_modes = (
                    "confirming_qty", "selecting", "payment",
                    "choosing_delivery_type",
                    "awaiting_delivery_address",
                    "awaiting_delivery_contact",
                    "awaiting_payment_resume",
                )
                _current_mode = await memory.get_mode()

                if (
                    (text_norm in _SOCIAL_WORDS or text_lower in _SOCIAL_WORDS
                     or text_rtrim in _SOCIAL_WORDS)
                    and _current_mode not in _stateful_modes
                ):
                    intent = "cancel"
                    answer = Humanizer.social_acknowledgment(tenant.persona_style)

                # ── Pre-DeepSeek fast-paths ───────────────────────────────────
                # These fire regardless of mode (they override mode where needed)

                # View cart — catches "my cart?", "what's in my cart?", "show cart" etc.
                if intent is None and _is_cart_query(text_norm, text_lower):
                    intent = "view_cart"

                # Store hours
                if intent is None and any(p in text_lower for p in _HOURS_PHRASES):
                    intent = "store_info"

                # Human handoff
                if intent is None and _is_human_handoff(text_lower):
                    intent = "human_handoff"

                # Start fresh
                if intent is None and text_lower in ("new", "start over", "restart"):
                    intent = "new_order"

                # Repeat order
                elif intent is None and text_lower in ("repeat", "same again", "same thing", "same order"):
                    intent = "repeat_order"

                # Confirm cash with order code
                elif intent is None and text_lower.startswith("confirm "):
                    potential_code = user_text.split(" ", 1)[1].strip().upper()
                    if len(potential_code) == 8 and potential_code.isalnum():
                        intent = "confirm_cash"
                        intent_payload["order_code"] = potential_code

                # Order status
                elif intent is None and any(text_lower.startswith(p) for p in _STATUS_PREFIXES):
                    intent = "order_status"
                    parts = user_text.split(" ", 1)
                    intent_payload["order_code"] = (
                        parts[1].strip().upper() if len(parts) > 1 else ""
                    )

                # ── DeepSeek path ─────────────────────────────────────────────
                if intent is None:

                    # Bare digit in non-stateful mode → session expired
                    # FIX: also exclude awaiting_payment_resume so a digit doesn't
                    # trigger search_expired while the payment resume flow is active.
                    if (
                        user_text.isdigit()
                        and _current_mode not in (
                            "selecting", "payment", "confirming_qty",
                            "choosing_delivery_type",
                            "awaiting_delivery_address",
                            "awaiting_delivery_contact",
                            "awaiting_payment_resume",
                            "shopping",
                        )
                    ):
                        await release_user_lock(
                            merchant_id=merchant_id,
                            user_phone=user_phone,
                            lock_value=request_id,
                        )
                        await send_whatsapp_message(
                            to_number=user_phone,
                            message=Humanizer.search_expired(),
                            phone_number_id=phone_number_id,
                        )
                        return

                    # Flag category browse so DeepSeek knows the expected intent
                    if _is_category_browse(text_lower) and _current_mode not in _stateful_modes:
                        intent = "product_inquiry"
                        intent_payload = {"intent": "product_inquiry", "catalogue_answer": None}

                    # DeepSeek classification
                    try:
                        conversation_history = await get_history(
                            client_id=client_id,
                            user_id=user_phone,
                        )
                        # get_history() returns newest-first (LPUSH order); DeepSeek expects oldest-first.
                        # Reverse so classify_intent receives chronological order.
                        if getattr(settings, 'DEBUG', False) and len(conversation_history) >= 2:
                            assert conversation_history[0]["timestamp"] >= conversation_history[-1]["timestamp"], \
                                "get_history() did not return newest-first"
                        conversation_history = list(reversed(conversation_history))

                        # FIX: build cart summary and pass to DeepSeek so it has full context
                        # of what the customer has in their cart when classifying intent.
                        # Previously hardcoded to None — the LLM was flying blind mid-conversation.
                        _cart_summary_dict = await cart_svc.get_cart_summary(
                            merchant_id=merchant_id,
                            client_id=client_id,
                            user_id=user_phone,
                        )
                        cart_summary = _format_cart_summary(_cart_summary_dict)

                        raw_intent = await classify_intent(
                            message=user_text,
                            store_name=tenant.client_name or str(client_id),
                            assistant_name=tenant.assistant_name,
                            assistant_personality=tenant.assistant_personality,
                            catalogue_context=catalogue_ctx,
                            history=conversation_history,
                            cart_summary=cart_summary,
                            last_intent=await memory.get("last_intent"),
                        )

                        intent         = raw_intent.get("intent", "other")
                        intent_payload = raw_intent

                        # Promote order_code from DeepSeek for natural-language order_status
                        # e.g. "where's my order X7K4M2PQ" now populates intent_payload correctly
                        if intent == "order_status" and raw_intent.get("order_code"):
                            intent_payload["order_code"] = raw_intent["order_code"]

                        # ── Name extraction & cleaning ────────────────────────
                        if raw_intent.get("customer_name"):
                            raw_name   = raw_intent["customer_name"].strip()[:100]
                            name_lower = raw_name.lower()
                            _NAME_PREFIXES = (
                                "call me ", "my name is ", "i am ", "i'm ",
                                "it's ", "they call me ", "just call me ", "name is ",
                            )
                            for prefix in _NAME_PREFIXES:
                                if name_lower.startswith(prefix):
                                    raw_name   = raw_name[len(prefix):].strip()
                                    name_lower = name_lower[len(prefix):]
                                    break
                            _name_words = raw_name.split()
                            if len(_name_words) > 2:
                                raw_name = _name_words[0]
                            raw_name = raw_name.rstrip(".,!?").strip()
                            if raw_name:
                                raw_name = raw_name[0].upper() + raw_name[1:]
                                if not await memory.get_customer_name():
                                    await memory.set_customer_name(raw_name)

                    except Exception:
                        logger.exception("classify_intent failed")
                        intent = "other"

                    # ── Bare number word in shopping mode → quantity update ────
                    if intent in ("other", "product_search") and _current_mode == "shopping":
                        qty = _extract_number_word(user_text)
                        if qty is not None:
                            intent = "update_quantity"
                            intent_payload = {
                                "intent": "update_quantity",
                                "quantity_updates": [{"name": None, "quantity": qty, "item_index": None}],
                            }

                # ── Handle catalogue-answerable intents ───────────────────────
                if intent in (
                    "product_inquiry",
                    "availability_check",
                    "price_check",
                    "alternative_request",
                ):
                    catalogue_answer = intent_payload.get("catalogue_answer")
                    if catalogue_answer:
                        answer = catalogue_answer
                    else:
                        intent = "product_search"
                        intent_payload["search_query"] = user_text

                # ── Fallback: unknown intent → product search ─────────────────
                if intent == "other" and not user_text.isdigit():
                    _in_waiting_mode = _current_mode in _stateful_modes
                    if (not _in_waiting_mode and (
                            text_norm in _SOCIAL_WORDS or text_lower in _SOCIAL_WORDS
                            or text_rtrim in _SOCIAL_WORDS
                            or (len(user_text.split()) <= 2 and text_norm in {
                                "ok", "k", "kk", "yep", "yup", "yeah", "ya",
                                "uh huh", "sure", "right", "true", "indeed",
                                "oya", "e good", "correct",
                            }))):
                        answer = Humanizer.social_acknowledgment(tenant.persona_style)
                    else:
                        intent = "product_search"
                        intent_payload["search_query"] = user_text

                if intent == "select_by_number":
                    intent_payload["search_query"] = None

                if answer is None:
                    answer = await router.route(
                        intent=intent,
                        intent_payload=intent_payload,
                    )

                if _closed_notice and answer:
                    answer = _closed_notice + answer

                await memory.add_user(user_text)
                await memory.add_assistant(answer)
                await memory.set("last_intent", intent)

    except Exception:
        logger.exception("WhatsApp handler failure")
        answer = Humanizer.error("generic")

    finally:
        await release_user_lock(
            merchant_id=merchant_id,
            user_phone=user_phone,
            lock_value=request_id,
        )

    if answer:
        await send_whatsapp_message(
            to_number=user_phone,
            message=answer,
            phone_number_id=phone_number_id,
        )
