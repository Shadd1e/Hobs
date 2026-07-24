# app/api/v1/workers/reminder_job.py
"""
Idle-draft reminder job for the onboarding wizard.

Not a scheduler itself — this just contains the logic. It's triggered by
POST /internal/cron/onboarding-reminders (see app/api/v1/internal_cron.py),
which you point an actual scheduler at: a Railway Cron Job, or any external
cron service (cron-job.org, GitHub Actions schedule, etc.) hitting that
endpoint roughly once an hour.

Reminder cadence (3 touches, then stop):
  1st reminder: 1 hour after the draft went idle
  2nd reminder: 48 hours after the draft went idle
  3rd reminder: 7 days after the draft went idle, then no more

Stale draft cleanup: after 30 days idle with no further reminders pending,
the draft is purged of PII and marked "abandoned" rather than kept forever.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models.merchant_application import MerchantApplication

logger = logging.getLogger(__name__)

_REMINDER_DELAYS = {
    0: timedelta(hours=1),
    1: timedelta(hours=48),
    2: timedelta(days=7),
}
_MAX_REMINDERS = 3
_ABANDON_AFTER = timedelta(days=30)


def _resume_url(resume_token):
    import os
    app_url = os.getenv("APP_URL", "https://shopprhq.com")
    return f"{app_url}/get-started?resume={resume_token}"


async def send_draft_reminders(db) -> dict:
    """
    Scans draft applications and sends the next reminder email to any that
    are due, or purges them if they've been idle past the abandon window.
    Returns counts for logging/observability — call this from the cron
    endpoint and log/return what it reports.
    """
    from app.services.email_service import send_application_reminder_email
    from app.api.v1.workers.background_tasks import fire_and_forget

    now = datetime.now(timezone.utc)
    sent = 0
    abandoned = 0

    res = await db.execute(
        select(MerchantApplication).where(MerchantApplication.status == "draft")
    )
    drafts = res.scalars().all()

    for draft in drafts:
        if not draft.last_activity_at:
            continue
        idle_for = now - draft.last_activity_at

        # Abandon first — no point emailing someone we're about to purge.
        if idle_for >= _ABANDON_AFTER:
            draft.status = "abandoned"
            draft.full_name = "[redacted]"
            draft.phone_number = None
            draft.whatsapp_number = None
            draft.cac_number = None
            draft.bvn = None
            draft.nin = None
            draft.resume_token = None
            abandoned += 1
            continue

        if draft.reminder_count >= _MAX_REMINDERS:
            continue

        delay = _REMINDER_DELAYS.get(draft.reminder_count)
        if delay is None or idle_for < delay:
            continue
        # Already sent a reminder more recently than this step's delay implies — avoid double-sends.
        if draft.last_reminder_sent_at and (now - draft.last_reminder_sent_at) < timedelta(hours=1):
            continue
        if not draft.resume_token:
            continue

        reminder_number = draft.reminder_count + 1
        fire_and_forget(
            lambda draft=draft, reminder_number=reminder_number: send_application_reminder_email(
                to_email=draft.email,
                full_name=draft.full_name,
                resume_url=_resume_url(draft.resume_token),
                reminder_number=reminder_number,
                current_step=draft.current_step,
            ),
            name=f"send_application_reminder_email_{draft.id}",
        )
        draft.reminder_count = reminder_number
        draft.last_reminder_sent_at = now
        sent += 1

    await db.commit()
    logger.info("Reminder job: sent=%d abandoned=%d scanned=%d", sent, abandoned, len(drafts))
    return {"sent": sent, "abandoned": abandoned, "scanned": len(drafts)}
