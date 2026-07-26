# app/api/v1/workers/checkout_reminder_job.py
"""
Pre-checkout reminder job for guests. Same shape as reminder_job.py
(onboarding drafts) — not a scheduler itself, just the logic. Triggered by
POST /internal/cron/checkout-reminders (see app/api/v1/internal_cron.py),
which you point a real scheduler at (Railway Cron Job or any external
cron service) hitting roughly hourly.

Unlike the onboarding job's 3-touch cadence, this is a single reminder:
fires once, N hours before check_out, for any CHECKED_IN booking that
hasn't had one sent yet. RoomBooking.reminder_sent_at is the guard against
double-sends (see RoomBooking.get_bookings_needing_checkout_reminder).
"""
import logging
from typing import Optional

from sqlalchemy import select

from app.models.room_booking import RoomBooking
from app.models.room import Room
from app.models.room_type import RoomType
from app.models.client_model import Client
from app.models.client_whatsapp_credential import ClientWhatsAppCredential

logger = logging.getLogger(__name__)

_REMINDER_HOURS_BEFORE = 3


async def send_checkout_reminders(db, hours_before: int = _REMINDER_HOURS_BEFORE) -> dict:
    from app.services.whatsapp_sender import send_whatsapp_message
    from app.conversation.hotel_humanizer import HotelHumanizer
    from app.api.v1.workers.background_tasks import fire_and_forget
    from datetime import datetime, timezone

    sent = 0
    skipped_no_phone = 0

    due_bookings = await RoomBooking.get_bookings_needing_checkout_reminder(db, hours_before=hours_before)

    for booking in due_bookings:
        if not booking.guest_phone:
            skipped_no_phone += 1
            continue

        client_result = await db.execute(select(Client).where(Client.id == booking.client_id))
        client_obj = client_result.scalar_one_or_none()
        hotel_name = client_obj.name if client_obj else "the hotel"

        cred_result = await db.execute(
            select(ClientWhatsAppCredential).where(
                ClientWhatsAppCredential.client_id == booking.client_id,
                ClientWhatsAppCredential.active.is_(True),
            )
        )
        cred = cred_result.scalar_one_or_none()
        if not cred:
            skipped_no_phone += 1
            continue

        message = HotelHumanizer.checkout_reminder(
            hotel_name, booking.check_out.isoformat(), booking.guest_name
        )

        fire_and_forget(
            lambda phone=booking.guest_phone, msg=message, pnid=cred.phone_number_id: send_whatsapp_message(
                to_number=phone, message=msg, phone_number_id=pnid,
            ),
            name=f"checkout_reminder_{booking.id}",
        )

        booking.reminder_sent_at = datetime.now(timezone.utc)
        sent += 1

    await db.commit()
    logger.info(
        "Checkout reminder job: sent=%d skipped_no_phone=%d scanned=%d",
        sent, skipped_no_phone, len(due_bookings),
    )
    return {"sent": sent, "skipped_no_phone": skipped_no_phone, "scanned": len(due_bookings)}
