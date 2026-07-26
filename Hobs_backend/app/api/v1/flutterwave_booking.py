# app/api/v1/flutterwave_booking.py
#
# Payment webhook for HoBS room bookings. Deliberately separate from
# app/api/v1/paystack.py — that route confirms Order/Cart (shop domain) via
# the real Paystack API and HMAC-SHA512 signature. This route confirms
# RoomBooking via the real Flutterwave API, and Flutterwave's webhook
# verification is structurally different: a direct secret-hash comparison
# on the `verif-hash` header, not an HMAC digest. See docs/WIRING_NOTES.md.

import os
import hmac
import logging
from decimal import Decimal

from fastapi import APIRouter, Request, HTTPException
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.room_booking import RoomBooking, BookingStatus
from app.models.room import Room
from app.models.room_type import RoomType
from app.models.client_model import Client
from app.models.client_whatsapp_credential import ClientWhatsAppCredential
from app.services.booking_service import BookingService, BookingConflictError
from app.services.whatsapp_sender import send_whatsapp_message
from app.conversation.hotel_humanizer import HotelHumanizer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["Flutterwave Bookings"])


def _verify_flutterwave_signature(received_hash: str) -> bool:
    """
    Flutterwave's scheme: you set a fixed "Secret Hash" string in the
    Flutterwave dashboard's webhook settings, and Flutterwave echoes that
    exact string back in the verif-hash header on every call — a direct
    string comparison, not an HMAC computed over the request body (unlike
    Paystack's x-paystack-signature).

    Deliberately reads PAYSTACK_WEBHOOK_SECRET — holds the Flutterwave
    secret hash in this deployment. See docs/WIRING_NOTES.md.
    """
    secret = os.getenv("PAYSTACK_WEBHOOK_SECRET", "")
    if not secret:
        logger.error("PAYSTACK_WEBHOOK_SECRET not set (holds the Flutterwave webhook secret hash)")
        return False
    if not received_hash:
        return False
    return hmac.compare_digest(secret, received_hash)


@router.post("/flutterwave-booking")
async def flutterwave_booking_webhook(request: Request):
    received_hash = request.headers.get("verif-hash", "")

    logger.info("Flutterwave booking webhook hit — hash_present=%s", bool(received_hash))

    if not _verify_flutterwave_signature(received_hash):
        logger.error("Flutterwave booking webhook: signature mismatch")
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event = payload.get("event")
    data = payload.get("data", {})

    # Flutterwave's success event name for standard payments.
    if event != "charge.completed" or data.get("status") != "successful":
        logger.info("Flutterwave booking webhook: ignoring event=%r status=%r", event, data.get("status"))
        return {"status": "ignored"}

    tx_ref = data.get("tx_ref")
    if not tx_ref:
        return {"status": "invalid"}

    webhook_amount = float(data.get("amount", 0))
    flw_ref = data.get("flw_ref") or data.get("id") or tx_ref

    logger.info("Flutterwave charge.completed — tx_ref=%s amount=%.2f", tx_ref, webhook_amount)

    # Redis dedup — same pattern as paystack.py, separate key namespace.
    from app.core.redis_client import redis_service
    dedup_key = f"flutterwave_booking_processed:{tx_ref}"
    try:
        rc = await redis_service.get_client()
        if await rc.get(dedup_key):
            logger.info("Duplicate Flutterwave booking webhook ignored: %s", tx_ref)
            return {"status": "duplicate"}
    except Exception as e:
        logger.warning("Redis dedup check failed, proceeding: %s", e)

    guest_phone = None
    phone_number_id = None
    hotel_name = None
    room_type_name = None
    check_in_str = None
    check_out_str = None
    booking_code = None

    async with AsyncSessionLocal() as db:
        async with db.begin():
            # tx_ref was set to booking.booking_code at payment-link creation
            # time (see BookingService.create_flutterwave_payment_link).
            result = await db.execute(
                select(RoomBooking).where(RoomBooking.booking_code == tx_ref).with_for_update()
            )
            booking = result.scalar_one_or_none()

            if not booking:
                logger.error("Flutterwave booking webhook: no booking found for tx_ref=%s", tx_ref)
                try:
                    from app.infrastructure.alerting.slack import alert
                    from app.api.v1.workers.background_tasks import fire_and_forget
                    fire_and_forget(alert(
                        title="Flutterwave Booking: Booking Not Found",
                        detail="Payment succeeded but no matching RoomBooking was found.",
                        level="critical",
                        fields={"tx_ref": tx_ref},
                    ), name="alert_flutterwave_booking_missing")
                except Exception:
                    pass
                return {"status": "booking_missing"}

            if booking.status == BookingStatus.PAID:
                logger.info("Flutterwave booking webhook: booking %s already paid", booking.id)
                return {"status": "already_paid"}

            expected_amount = float(booking.total_amount)
            if abs(webhook_amount - expected_amount) > 0.01:
                logger.error(
                    "Flutterwave booking amount mismatch — expected=%.2f webhook=%.2f tx_ref=%s",
                    expected_amount, webhook_amount, tx_ref,
                )
                try:
                    from app.infrastructure.alerting.slack import alert
                    from app.api.v1.workers.background_tasks import fire_and_forget
                    fire_and_forget(alert(
                        title="Flutterwave Booking Amount Mismatch ⚠️",
                        detail="Webhook amount does not match booking total.",
                        level="critical",
                        fields={
                            "tx_ref": tx_ref,
                            "expected": f"₦{expected_amount:,.2f}",
                            "received": f"₦{webhook_amount:,.2f}",
                            "booking_id": str(booking.id),
                        },
                    ), name="alert_flutterwave_booking_amount_mismatch")
                except Exception:
                    pass
                raise HTTPException(status_code=422, detail="Amount mismatch")

            booking_service = BookingService(db)
            try:
                booking = await booking_service.confirm_payment(
                    booking_id=booking.id,
                    payment_ref=str(flw_ref),
                    amount_paid=Decimal(str(webhook_amount)),
                )
            except BookingConflictError as conflict_err:
                # Double booking surfaced at payment-confirm time — the
                # known tradeoff from the "lock only on PAID" decision.
                # Booking has already been auto-cancelled inside
                # confirm_payment(); this needs a real refund, which isn't
                # automated yet — alert loudly so a human handles it.
                logger.error("Flutterwave booking conflict for tx_ref=%s: %s", tx_ref, conflict_err)
                try:
                    from app.infrastructure.alerting.slack import alert
                    from app.api.v1.workers.background_tasks import fire_and_forget
                    fire_and_forget(alert(
                        title="Flutterwave Booking: Double-Booking Conflict — REFUND NEEDED",
                        detail=str(conflict_err),
                        level="critical",
                        fields={"tx_ref": tx_ref, "amount": f"₦{webhook_amount:,.2f}"},
                    ), name="alert_flutterwave_booking_conflict")
                except Exception:
                    pass
                return {"status": "conflict_cancelled_needs_refund"}

            booking_code = booking.booking_code
            guest_phone = booking.guest_phone

            room_result = await db.execute(select(Room).where(Room.id == booking.room_id))
            room = room_result.scalar_one_or_none()
            if room:
                rt_result = await db.execute(select(RoomType).where(RoomType.id == room.room_type_id))
                room_type = rt_result.scalar_one_or_none()
                room_type_name = room_type.name if room_type else None

            check_in_str = booking.check_in.isoformat()
            check_out_str = booking.check_out.isoformat()

            client_result = await db.execute(select(Client).where(Client.id == booking.client_id))
            client_obj = client_result.scalar_one_or_none()
            hotel_name = client_obj.name if client_obj else None

            cred_result = await db.execute(
                select(ClientWhatsAppCredential).where(
                    ClientWhatsAppCredential.client_id == booking.client_id,
                    ClientWhatsAppCredential.active.is_(True),
                )
            )
            cred = cred_result.scalar_one_or_none()
            if cred:
                phone_number_id = cred.phone_number_id

            await db.flush()

    try:
        rc = await redis_service.get_client()
        await rc.setex(dedup_key, 86400, "1")
    except Exception as e:
        logger.warning("Redis dedup mark failed: %s", e)

    logger.info(
        "[BOOKING_PAYMENT_SUCCESS] booking_code=%s tx_ref=%s amount=%.2f",
        booking_code, tx_ref, webhook_amount,
    )

    if guest_phone and phone_number_id and booking_code:
        try:
            await send_whatsapp_message(
                to_number=guest_phone,
                message=HotelHumanizer.booking_confirmed_guest(
                    hotel_name or "the hotel",
                    room_type_name or "your room",
                    check_in_str, check_out_str, booking_code,
                ),
                phone_number_id=phone_number_id,
            )
        except Exception as notify_err:
            logger.error("Failed to send booking confirmation to %s: %s", guest_phone, notify_err)

    return {"status": "ok"}
