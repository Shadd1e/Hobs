# app/api/v1/workers/admin_review_nudge_job.py
"""
Nudges ADMINS (not applicants) about verification submissions sitting
unreviewed. Every submitted CAC/BVN/NIN goes to manual review — the onus is
on an admin to actually approve or reject it via:
    POST /admin/whatsapp-setup/applications/{id}/verification/approve
    POST /admin/whatsapp-setup/applications/{id}/verification/reject
This job doesn't touch the application itself; it only makes sure the
review doesn't sit forgotten. Complements verification_grace_job.py, which
nudges the *applicant* when they submitted nothing at all — this one is
for the case where they DID submit and it's now on us.

Triggered by POST /internal/cron/admin-review-nudges (see internal_cron.py).
Suggested cadence: same scheduler as the other two, once an hour is fine —
_MIN_REVIEW_AGE and _RENUDGE_GAP below control actual send frequency.

WhatsApp delivery requires two env vars that don't otherwise exist in this
codebase yet:
    HOBS_OPS_PHONE_NUMBER_ID     — a Meta WhatsApp Business phone_number_id
                                    to send FROM (an internal ops number)
    HOBS_ADMIN_WHATSAPP_NUMBERS  — comma-separated recipient numbers, e.g.
                                    "2348012345678,2349087654321"
If either is unset, WhatsApp delivery is skipped (logged, not raised) and
the Slack alert still fires — Slack alone is enough to not go silent.
"""
import os
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models.merchant_application import MerchantApplication

logger = logging.getLogger(__name__)

_MIN_REVIEW_AGE = timedelta(hours=24)   # don't nudge until it's been sitting a day
_RENUDGE_GAP    = timedelta(hours=24)   # then repeat once a day until resolved


def _admin_whatsapp_numbers() -> list:
    raw = os.getenv("HOBS_ADMIN_WHATSAPP_NUMBERS", "")
    return [n.strip() for n in raw.split(",") if n.strip()]


async def send_admin_review_nudges(db) -> dict:
    from app.infrastructure.alerting.slack import alert
    from app.api.v1.workers.background_tasks import fire_and_forget

    now = datetime.now(timezone.utc)

    res = await db.execute(
        select(MerchantApplication).where(
            MerchantApplication.verification_status == "pending_manual_review",
            MerchantApplication.verification_reviewed_at.is_(None),
        )
    )
    apps = res.scalars().all()

    due = []
    for app in apps:
        if not app.created_at or (now - app.created_at) < _MIN_REVIEW_AGE:
            continue
        if app.last_admin_review_nudge_at and (now - app.last_admin_review_nudge_at) < _RENUDGE_GAP:
            continue
        due.append(app)

    if not due:
        return {"nudged": 0, "scanned": len(apps)}

    lines = [
        f"• *{a.business_name or a.full_name}* — submitted via {a.verification_method}, "
        f"waiting {round((now - a.created_at).total_seconds() / 3600)}h "
        f"(application {a.id})"
        for a in due
    ]
    detail = (
        f"{len(due)} verification submission(s) waiting on manual review:\n"
        + "\n".join(lines)
        + "\n\nReview here: /admin (Applications tab)"
    )

    fire_and_forget(
        alert(title="Verification reviews pending", level="warning", detail=detail),
        name="admin_review_nudge_slack",
    )

    phone_number_id = os.getenv("HOBS_OPS_PHONE_NUMBER_ID", "")
    admin_numbers = _admin_whatsapp_numbers()
    if phone_number_id and admin_numbers:
        from app.services.whatsapp_sender import send_whatsapp_message

        wa_text = (
            f"⚠️ {len(due)} merchant verification submission(s) waiting on review "
            f"(oldest {round((now - due[0].created_at).total_seconds() / 3600)}h).\n"
            f"Check the admin dashboard when you get a chance."
        )
        for number in admin_numbers:
            fire_and_forget(
                send_whatsapp_message(to_number=number, message=wa_text, phone_number_id=phone_number_id),
                name=f"admin_review_nudge_wa_{number}",
            )
    else:
        logger.info(
            "Admin WhatsApp nudge skipped (HOBS_OPS_PHONE_NUMBER_ID / "
            "HOBS_ADMIN_WHATSAPP_NUMBERS not configured) — Slack alert still sent."
        )

    for app in due:
        app.last_admin_review_nudge_at = now
    await db.commit()

    return {"nudged": len(due), "scanned": len(apps)}
