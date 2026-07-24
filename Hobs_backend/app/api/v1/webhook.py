# app/api/v1/webhook.py

import json
import os
import hmac
import hashlib
import logging

from fastapi import APIRouter, Request, Query, HTTPException
from fastapi.responses import PlainTextResponse

from app.core.tenant_resolver import resolve_tenant_by_phone_number_id
from app.orchestrators.whatsapp_handler import handle_whatsapp_message
from app.core.redis_client import seen_wamid, redis_service
from app.db.session import AsyncSessionLocal
from app.core.request_context import request_id_var
from app.conversation.name_parser import parse_customer_name  # FIX: shared helper

router = APIRouter()
logger = logging.getLogger(__name__)

META_VERIFY_TOKEN = os.getenv("META_VERIFY_TOKEN")


# ==================================================
# META VERIFY ENDPOINT
# ==================================================

@router.get("/webhook/whatsapp")
async def verify_webhook(
    hub_mode: str = Query(..., alias="hub.mode"),
    hub_verify_token: str = Query(..., alias="hub.verify_token"),
    hub_challenge: str = Query(..., alias="hub.challenge"),
):
    if hub_mode == "subscribe" and hub_verify_token == META_VERIFY_TOKEN:
        return PlainTextResponse(hub_challenge)
    raise HTTPException(status_code=403)


# ==================================================
# SIGNATURE VERIFICATION HELPER
# ==================================================

def _verify_meta_signature(raw_body: bytes, signature_header: str) -> bool:
    app_secret = os.getenv("META_APP_SECRET", "")

    if not app_secret:
        logger.error(
            "META_APP_SECRET not set — rejecting webhook request. "
            "Set this env var to enable signature verification."
        )
        return False

    if not signature_header:
        logger.warning("Webhook received with no X-Hub-Signature-256 header")
        return False

    if not signature_header.startswith("sha256="):
        logger.warning("Unexpected signature format: %s", signature_header[:20])
        return False

    expected = hmac.new(
        app_secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    received = signature_header[7:]
    return hmac.compare_digest(expected, received)


# ==================================================
# WHATSAPP MAIN WEBHOOK
# ==================================================

@router.post("/webhook/whatsapp")
async def receive_webhook(request: Request):
    raw_body = await request.body()

    if not raw_body:
        return {"status": "empty"}

    import uuid as _uuid
    _req_id = str(_uuid.uuid4())[:8]
    request_id_var.set(_req_id)
    logger.info("Webhook received request_id=%s", _req_id)

    # ==================================================
    # SIGNATURE VERIFICATION
    # ==================================================
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not _verify_meta_signature(raw_body, signature):
        logger.error("Webhook signature mismatch — rejecting request")
        try:
            import asyncio
            from app.core.redis_client import should_send_webhook_alert
            from app.infrastructure.alerting.slack import alert
            # Every mismatch is logged above regardless — this only caps how
            # often it also pages Slack, so a flood of junk requests can't
            # drown out real alerts or blow through Slack's own rate limit.
            if await should_send_webhook_alert():
                asyncio.create_task(alert(
                    title="Webhook Signature Mismatch",
                    detail=(
                        "An inbound webhook failed signature verification. "
                        "Further mismatches in the next 5 minutes are logged but won't re-alert."
                    ),
                    level="warning",
                    fields={
                        "IP":        request.client.host if request.client else "unknown",
                        "Signature": signature[:40] + "..." if len(signature) > 40 else signature or "none",
                    },
                ))
        except Exception:
            pass
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        payload = json.loads(raw_body.decode())
    except json.JSONDecodeError:
        logger.error("Invalid JSON payload")
        return {"status": "invalid_json"}

    entries = payload.get("entry", [])
    if not entries:
        return {"status": "no_entries"}

    for entry in entries:

        changes = entry.get("changes", [])
        if not changes:
            continue

        for change in changes:

            value = change.get("value", {})

            if "statuses" in value:
                continue

            messages = value.get("messages", [])
            if not messages:
                continue

            metadata        = value.get("metadata", {})
            phone_number_id = metadata.get("phone_number_id")

            if not phone_number_id:
                logger.warning("Missing phone_number_id")
                continue

            message_data = messages[0]

            wamid       = message_data.get("id")
            from_number = message_data.get("from")

            if not wamid or not from_number:
                continue

            from_number = from_number.replace("+", "").strip()

            # ==================================================
            # WAMID DEDUP (ATOMIC)
            # ==================================================
            try:
                is_new = await seen_wamid(wamid)
            except Exception as e:
                logger.exception("Redis failure during dedup: %s", e)
                continue

            if not is_new:
                continue

            # ==================================================
            # PER-SENDER RATE LIMIT
            # ==================================================
            try:
                _rl_client = await redis_service.get_client()
                _rl_key    = f"wa:inbound_rate:{from_number}"
                _rl_count  = await _rl_client.incr(_rl_key)
                if _rl_count == 1:
                    await _rl_client.expire(_rl_key, 60)
                if _rl_count > 10:
                    logger.warning(
                        "Per-sender rate limit exceeded for %s (%d msgs/min) — dropping",
                        from_number, _rl_count,
                    )
                    continue
            except Exception as _rl_err:
                logger.warning("Inbound rate-limit check failed (non-fatal): %s", _rl_err)

            msg_type = message_data.get("type", "text")

            # ==================================================
            # NON-TEXT MESSAGE HANDLING
            # FIX: tenant resolution and reply now share a single DB session.
            # A send failure is logged but does not swallow the continue — the
            # message is still skipped so we don't fall through to the orchestrator.
            # ==================================================

            if msg_type != "text":
                logger.info("Non-text message type=%s from=%s", msg_type, from_number)

                tenant_context = None
                try:
                    async with AsyncSessionLocal() as db:
                        # single session for both resolve + (no DB work needed for send)
                        tenant_context = await resolve_tenant_by_phone_number_id(
                            db, phone_number_id
                        )
                except Exception:
                    logger.exception("Tenant resolution failed for non-text reply")
                    continue

                if tenant_context:
                    from app.services.whatsapp_sender import send_whatsapp_message
                    from app.conversation.humanizer import Humanizer

                    reply = (
                        Humanizer.voice_note_reply()
                        if msg_type == "audio"
                        else (
                            "I'm sorry, I can only read text messages right now. "
                            "Could you type what you need? 😊"
                        )
                    )

                    try:
                        await send_whatsapp_message(
                            to_number=from_number,
                            message=reply,
                            phone_number_id=phone_number_id,
                        )
                    except Exception:
                        # Log but still continue — message handled, don't fall through
                        logger.exception(
                            "Failed to send non-text reply to %s — message dropped", from_number
                        )
                continue

            # ==================================================
            # TENANT RESOLUTION
            # ==================================================
            try:
                async with AsyncSessionLocal() as db:
                    tenant_context = await resolve_tenant_by_phone_number_id(
                        db, phone_number_id
                    )
            except Exception as e:
                logger.exception("Tenant resolution failed: %s", e)
                continue

            if not tenant_context:
                logger.error("No tenant found for phone_number_id: %s", phone_number_id)
                continue

            user_text = message_data.get("text", {}).get("body", "").strip()

            # ==================================================
            # FIRST-TIME / NAME CAPTURE
            # FIX: name cleaning now delegates to parse_customer_name()
            # instead of duplicating the strip logic here.
            # ==================================================

            try:
                async with AsyncSessionLocal() as db:
                    async with db.begin():
                        from app.services.customer_context import CustomerContextService
                        from app.conversation.memory import ConversationMemory
                        from app.services.whatsapp_sender import send_whatsapp_message
                        from app.conversation.humanizer import Humanizer

                        ctx_svc = CustomerContextService()
                        profile, is_new_customer = await ctx_svc.touch_profile(
                            db=db,
                            phone_number=from_number,
                        )

                        # ── New-customer admin alert ─────────────────────────
                        # Fires once, on the very first message this phone
                        # number has ever sent to ANY store on the platform.
                        # Mirrors the merchant-onboarding alerts elsewhere
                        # (see client_api.py / admin_whatsapp.py) so admin
                        # gets a Slack ping whenever anyone — merchant or
                        # customer — onboards, not just merchants.
                        if is_new_customer:
                            try:
                                from app.infrastructure.alerting.slack import alert
                                from app.services.merchant_service import MerchantService as _MS
                                from app.api.v1.workers.background_tasks import fire_and_forget

                                _merchant = await _MS(db).get(tenant_context.merchant_id)
                                fire_and_forget(alert(
                                    title="New Customer Onboarded",
                                    detail=(
                                        f"A new customer just messaged "
                                        f"*{tenant_context.client_name or tenant_context.client_id}* "
                                        f"for the first time on WhatsApp."
                                    ),
                                    level="info",
                                    fields={
                                        "Customer Phone": f"+{from_number}",
                                        "Store":           tenant_context.client_name or "—",
                                        "Store ID":        str(tenant_context.client_id),
                                        "Merchant":        _merchant.name if _merchant else "—",
                                        "Merchant ID":     str(tenant_context.merchant_id),
                                    },
                                ), name="slack_new_customer_onboarded")
                            except Exception as _e:
                                logger.warning(
                                    "New-customer Slack alert failed (non-fatal): %s", _e
                                )

                        memory = await ConversationMemory.load(
                            str(tenant_context.client_id),
                            from_number,
                        )
                        current_mode = await memory.get_mode()

                        # ── Mode: awaiting_name ──────────────────────────────
                        if current_mode == "awaiting_name":
                            # FIX: was copy-pasted inline — now uses shared helper
                            name = parse_customer_name(user_text)
                            if not name:
                                name = user_text.strip()[:50]

                            await ctx_svc.save_name(
                                db=db,
                                phone_number=from_number,
                                name=name,
                            )
                            await memory.set_customer_name(name)
                            await memory.set_mode("idle")

                            store_name = tenant_context.client_name or tenant_context.client_id
                            welcome    = Humanizer.name_saved(name, store_name)

                            await send_whatsapp_message(
                                to_number=from_number,
                                message=welcome,
                                phone_number_id=phone_number_id,
                            )
                            continue

                        # ── First-time customer ──────────────────────────────
                        is_first_time    = CustomerContextService.is_first_time(profile)
                        already_welcomed = await memory.get("welcomed", False)

                        if is_first_time and not already_welcomed:
                            await memory.set("welcomed", True)
                            await memory.set("pending_name_prompt", True)

                        # ── Sync name from DB if Redis TTL expired ───────────
                        session_name = await memory.get_customer_name()
                        if not session_name and profile and profile.is_named:
                            await memory.set_customer_name(profile.name)

                        # ── Repeat-order prompt ──────────────────────────────
                        if (
                            profile
                            and profile.is_named
                            and not already_welcomed
                            and user_text.strip().lower() in {
                                "hi", "hello", "hey", "good morning",
                                "good afternoon", "good evening", "heyy",
                            }
                        ):
                            last_order = profile.get_last_order()
                            if (
                                last_order
                                and profile.last_order_client_id == str(tenant_context.client_id)
                            ):
                                already_offered = await memory.get("repeat_order_offered", False)
                                if not already_offered:
                                    await memory.set("repeat_order_offered", True)
                                    items_text = ", ".join(
                                        f"{i['qty']}x {i['name']}"
                                        for i in last_order.get("items", [])[:3]
                                    )
                                    total_str = f"₦{last_order['total']:,.0f}"
                                    repeat_msg = (
                                        f"Welcome back, {profile.name}! 👋\n\n"
                                        f"Your last order was: *{items_text}* — {total_str}\n\n"
                                        f"Want the same again? Reply *repeat* or just tell me what you need."
                                    )
                                    await send_whatsapp_message(
                                        to_number=from_number,
                                        message=repeat_msg,
                                        phone_number_id=phone_number_id,
                                    )
                                    await memory.set("pending_repeat_order", last_order)
                                    continue

            except Exception:
                logger.exception(
                    "Customer profile / first-time check failed for %s", from_number
                )

            # ==================================================
            # FORWARD TO ORCHESTRATOR
            # ==================================================
            try:
                await handle_whatsapp_message(
                    tenant=tenant_context,
                    message_data=message_data,
                    phone_number_id=phone_number_id,
                )
            except Exception as e:
                logger.exception(
                    "Message handling failed for WAMID %s: %s", wamid, e
                )
                continue

    return {"status": "received"}
