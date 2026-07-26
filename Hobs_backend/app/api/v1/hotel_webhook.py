# app/api/v1/hotel_webhook.py
#
# Entry point for the hotel-side WhatsApp number(s). Deliberately a
# SEPARATE route from app/api/v1/webhook.py (the shop's webhook) — hotel
# numbers live on their own Meta App/WABA (set up earlier, separate from
# ShoprHQ's), so this has its own verify token, app secret, and endpoint
# path rather than trying to share /webhook/whatsapp.
#
# This file's only job is: verify -> parse -> dedup -> decide guest vs
# staff -> dispatch -> reply. All actual conversation logic lives in
# BookingOrchestrator / HotelConversationRouter (guest) and
# StaffOrchestrator (staff) -- nothing here should grow business logic.

import json
import os
import hmac
import hashlib
import logging

from fastapi import APIRouter, Request, Query, HTTPException
from fastapi.responses import PlainTextResponse

from app.core.tenant_resolver import resolve_tenant_by_phone_number_id
from app.core.redis_client import seen_wamid
from app.db.session import AsyncSessionLocal

router = APIRouter()
logger = logging.getLogger(__name__)

# New, hotel-specific env vars -- this Meta App is genuinely new (not
# inherited ShoprHQ config), so no "paystack-naming" style situation here;
# named accurately from the start.
HOTEL_META_VERIFY_TOKEN = os.getenv("HOTEL_META_VERIFY_TOKEN")
HOTEL_META_APP_SECRET = os.getenv("HOTEL_META_APP_SECRET", "")


# ==================================================
# META VERIFY ENDPOINT
# ==================================================

@router.get("/webhook/hotel-whatsapp")
async def verify_hotel_webhook(
    hub_mode: str = Query(..., alias="hub.mode"),
    hub_verify_token: str = Query(..., alias="hub.verify_token"),
    hub_challenge: str = Query(..., alias="hub.challenge"),
):
    if hub_mode == "subscribe" and hub_verify_token == HOTEL_META_VERIFY_TOKEN:
        return PlainTextResponse(hub_challenge)
    raise HTTPException(status_code=403)


def _verify_meta_signature(raw_body: bytes, signature_header: str) -> bool:
    if not HOTEL_META_APP_SECRET:
        logger.error("HOTEL_META_APP_SECRET not set -- rejecting hotel webhook request")
        return False
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(HOTEL_META_APP_SECRET.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header[7:])


# ==================================================
# MAIN WEBHOOK
# ==================================================

@router.post("/webhook/hotel-whatsapp")
async def receive_hotel_webhook(request: Request):
    raw_body = await request.body()
    if not raw_body:
        return {"status": "empty"}

    signature = request.headers.get("X-Hub-Signature-256", "")
    if not _verify_meta_signature(raw_body, signature):
        logger.error("Hotel webhook signature mismatch -- rejecting request")
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        payload = json.loads(raw_body.decode())
    except json.JSONDecodeError:
        return {"status": "invalid_json"}

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})

            if "statuses" in value:
                continue

            messages = value.get("messages", [])
            if not messages:
                continue

            phone_number_id = value.get("metadata", {}).get("phone_number_id")
            if not phone_number_id:
                continue

            message_data = messages[0]
            wamid = message_data.get("id")
            from_number = message_data.get("from")
            if not wamid or not from_number:
                continue
            from_number = from_number.replace("+", "").strip()

            try:
                is_new = await seen_wamid(wamid)
            except Exception as e:
                logger.exception("Redis dedup failure (hotel webhook): %s", e)
                continue
            if not is_new:
                continue

            if message_data.get("type", "text") != "text":
                await _reply_non_text(from_number, phone_number_id)
                continue

            user_text = message_data.get("text", {}).get("body", "").strip()
            if not user_text:
                continue

            try:
                await _dispatch_message(phone_number_id, from_number, user_text)
            except Exception as e:
                logger.exception("Hotel message handling failed for WAMID %s: %s", wamid, e)
                continue

    return {"status": "received"}


async def _reply_non_text(from_number: str, phone_number_id: str):
    try:
        async with AsyncSessionLocal() as db:
            tenant = await resolve_tenant_by_phone_number_id(db, phone_number_id)
        if tenant:
            from app.services.whatsapp_sender import send_whatsapp_message
            await send_whatsapp_message(
                to_number=from_number,
                message="I can only read text messages right now -- could you type what you need? \U0001F60A",
                phone_number_id=phone_number_id,
            )
    except Exception:
        logger.exception("Failed to send non-text reply (hotel) to %s", from_number)


async def _dispatch_message(phone_number_id: str, from_number: str, user_text: str):
    from app.services.whatsapp_sender import send_whatsapp_message
    from app.orchestrators.staff_orchestrator import StaffOrchestrator

    async with AsyncSessionLocal() as db:
        async with db.begin():
            tenant = await resolve_tenant_by_phone_number_id(db, phone_number_id)
            if not tenant:
                logger.error("No hotel tenant found for phone_number_id=%s", phone_number_id)
                return

            merchant_id = str(tenant.merchant_id)
            client_id = str(tenant.client_id)

            # -- Staff check FIRST: staff and guests never share a flow --
            staff = await StaffOrchestrator.is_staff_number(db, client_id, from_number)
            if staff:
                orchestrator = StaffOrchestrator(db, merchant_id, client_id)
                reply = await orchestrator.handle_message(staff, user_text)
                await send_whatsapp_message(
                    to_number=from_number, message=reply, phone_number_id=phone_number_id,
                )
                return

            # -- Guest flow --
            reply = await _handle_guest_message(db, tenant, from_number, phone_number_id, user_text)

    await send_whatsapp_message(to_number=from_number, message=reply, phone_number_id=phone_number_id)


async def _handle_guest_message(db, tenant, from_number: str, phone_number_id: str, user_text: str) -> str:
    from app.conversation.memory import ConversationMemory
    from app.orchestrators.booking_context import BookingContext
    from app.orchestrators.hotel_conversation_router import HotelConversationRouter
    from app.services.booking_service import BookingService
    from app.services.room_type_service import RoomTypeService
    from app.services.room_service import RoomService
    from app.infrastructure.ai.booking_intent_service import classify_booking_intent

    merchant_id = str(tenant.merchant_id)
    client_id = str(tenant.client_id)

    memory = await ConversationMemory.load(client_id, from_number)

    room_type_service = RoomTypeService(db)
    room_types = await room_type_service.list_all(merchant_id=merchant_id, client_id=client_id)
    room_types_payload = [{"name": rt.name, "price": rt.price} for rt in room_types]

    current_mode = await memory.get_mode()

    # Modes that expect a raw reply (a name, yes/no) skip re-classification
    # against the full intent schema -- the router itself branches on mode
    # first, but we still need SOME intent_payload shape to pass through.
    if current_mode in ("confirming_booking_name",):
        intent_payload = {"guest_name": user_text}
        intent = "provide_guest_name"
    else:
        extracted = await classify_booking_intent(
            user_text, room_types=room_types_payload, current_mode=current_mode,
        )
        intent = extracted.get("intent", "other")
        intent_payload = extracted

    context = BookingContext(
        tenant=tenant,
        db=db,
        user_phone=from_number,
        user_text=user_text,
        phone_number_id=phone_number_id,
        memory=memory,
        booking_service=BookingService(db),
        room_type_service=room_type_service,
        room_service=RoomService(db),
    )

    router_ = HotelConversationRouter(context)
    return await router_.route(intent=intent, intent_payload=intent_payload)
