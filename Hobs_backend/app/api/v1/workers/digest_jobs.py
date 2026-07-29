# app/api/v1/workers/digest_jobs.py
#
# Two digests, same cron-job shape as checkout_reminder_job.py:
#   - weekly_staff_digest: cancellations/reverts per hotel, sent to
#     managers+ -- closes the "several small actions each under the
#     high-impact threshold" gap that per-action alerts alone miss.
#   - daily_owner_digest: plain occupancy summary sent unprompted to the
#     hotel's operator_notify_phone, the "bookkeeper in your pocket" feature.

import logging
from datetime import datetime, timezone
from sqlalchemy import select

logger = logging.getLogger(__name__)


async def send_weekly_staff_digests(db) -> dict:
    from app.models.client_model import Client
    from app.models.hotel_staff import HotelStaff
    from app.models.client_whatsapp_credential import ClientWhatsAppCredential
    from app.services.staff_audit_service import StaffAuditService
    from app.services.whatsapp_sender import send_whatsapp_message
    from app.api.v1.workers.background_tasks import fire_and_forget

    sent = 0
    hotels = (await db.execute(select(Client).where(Client.whatsapp_number.isnot(None)))).scalars().all()
    audit_service = StaffAuditService(db)

    for hotel in hotels:
        entries = await audit_service.get_weekly_cancellation_summary(hotel.id)
        if not entries:
            continue

        managers_stmt = select(HotelStaff).where(
            HotelStaff.client_id == hotel.id, HotelStaff.is_active.is_(True),
        )
        managers = [s for s in (await db.execute(managers_stmt)).scalars().all() if s.can_review_flagged_actions()]
        if not managers:
            continue

        cred = (await db.execute(
            select(ClientWhatsAppCredential).where(
                ClientWhatsAppCredential.client_id == hotel.id, ClientWhatsAppCredential.active.is_(True),
            )
        )).scalar_one_or_none()
        if not cred:
            continue

        unreviewed = sum(1 for e in entries if e.is_high_impact and not e.reviewed)
        message = (
            f"📊 *Weekly summary for {hotel.name}*\n"
            f"{len(entries)} cancellation/revert action(s) this week.\n"
            f"{unreviewed} still awaiting review.\n"
            f"Check the dashboard for details."
        )

        for manager in managers:
            fire_and_forget(
                send_whatsapp_message(to_number=manager.phone_number, message=message, phone_number_id=cred.phone_number_id),
                name=f"weekly_digest_{hotel.id}_{manager.id}",
            )
        sent += 1

    logger.info("Weekly staff digest: sent to %d hotel(s)", sent)
    return {"hotels_notified": sent}


async def send_daily_owner_digests(db) -> dict:
    from app.models.client_model import Client
    from app.models.client_whatsapp_credential import ClientWhatsAppCredential
    from app.services.room_service import RoomService
    from app.services.whatsapp_sender import send_whatsapp_message
    from app.api.v1.workers.background_tasks import fire_and_forget

    sent = 0
    hotels = (await db.execute(
        select(Client).where(Client.operator_notify_phone.isnot(None))
    )).scalars().all()

    room_service = RoomService(db)

    for hotel in hotels:
        grid = await room_service.dashboard_grid(hotel.merchant_id, hotel.id)
        if not grid:
            continue

        cred = (await db.execute(
            select(ClientWhatsAppCredential).where(
                ClientWhatsAppCredential.client_id == hotel.id, ClientWhatsAppCredential.active.is_(True),
            )
        )).scalar_one_or_none()
        if not cred:
            continue

        total = len(grid)
        booked = sum(1 for r in grid if r["is_booked_today"])
        occupancy_pct = round((booked / total) * 100) if total else 0

        message = (
            f"🏨 *{hotel.name} — daily summary*\n"
            f"{booked}/{total} rooms occupied ({occupancy_pct}%)\n"
            f"Have a good day!"
        )

        fire_and_forget(
            send_whatsapp_message(to_number=hotel.operator_notify_phone, message=message, phone_number_id=cred.phone_number_id),
            name=f"daily_digest_{hotel.id}",
        )
        sent += 1

    logger.info("Daily owner digest: sent to %d hotel(s)", sent)
    return {"hotels_notified": sent}
