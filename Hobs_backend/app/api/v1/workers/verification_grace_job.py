# app/api/v1/workers/verification_grace_job.py
"""
7-day verification grace-period job.

Applies to applications that finished the onboarding wizard WITHOUT
submitting CAC/BVN/NIN (verification_method is null, verification_skipped_at
is set — see apply_wizard_step_three / apply_wizard_step_four in
api/v1/merchant.py). Separate from app/api/v1/workers/reminder_job.py, which
handles a completely different case (idle, unfinished drafts).

Not a scheduler itself — triggered by POST /internal/cron/verification-grace
(see app/api/v1/internal_cron.py). Point an external cron at that endpoint
roughly once an hour; a daily trigger also works since the delay table below
is checked on every run and de-duped by last_verification_reminder_sent_at.

Reminder cadence (5 touches, then stop sending applicant emails):
  #1: day 2   #2: day 4   #3: day 6   #4: day 7 (morning)   #5: day 7 (evening)

Deliberately NOT automated: suspending messaging. Per product decision, this
job never sets Merchant.messaging_suspended_at itself. Once all 5 reminders
are exhausted and verification is still missing, it fires one Slack alert
and flags the application so admin can see it in the dashboard queue and
suspend messaging manually (POST /admin/whatsapp-setup/merchants/{id}/suspend-messaging).
This keeps a human in the loop on an action that affects a live merchant's
ability to talk to their customers.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models.merchant_application import MerchantApplication

logger = logging.getLogger(__name__)

# Offsets are all measured from verification_skipped_at.
_REMINDER_DELAYS = {
    0: timedelta(days=2),            # -> reminder #1
    1: timedelta(days=4),            # -> reminder #2
    2: timedelta(days=6),            # -> reminder #3
    3: timedelta(days=7),            # -> reminder #4 (morning of day 7)
    4: timedelta(days=7, hours=12),  # -> reminder #5 (evening of day 7)
}
_MAX_REMINDERS = 5
_MIN_GAP_BETWEEN_SENDS = timedelta(hours=6)  # de-dupe guard, mirrors reminder_job.py


def _resume_url(resume_token: str) -> str:
    import os
    app_url = os.getenv("APP_URL", "https://hobs.altekflo.xyz")
    return f"{app_url}/get-started?resume={resume_token}"


async def send_verification_grace_reminders(db) -> dict:
    """
    Scans applications mid-grace-period, sends the next due reminder email,
    and fires a one-time Slack + admin-dashboard alert for any that run out
    the clock still unverified. Returns counts for logging/observability.
    """
    from app.services.email_service import send_verification_grace_email
    from app.api.v1.workers.background_tasks import fire_and_forget

    now = datetime.now(timezone.utc)
    sent = 0
    alerted = 0

    res = await db.execute(
        select(MerchantApplication).where(
            MerchantApplication.verification_skipped_at.is_not(None),
            MerchantApplication.verification_method.is_(None),
            MerchantApplication.status.in_(("pending", "needs_attention", "approved")),
        )
    )
    apps = res.scalars().all()

    for app in apps:
        elapsed = now - app.verification_skipped_at

        # ── Applicant reminder emails (only while there's a live wizard to
        # resume — once rejected there's nothing to send them back to) ──
        if app.status != "rejected" and app.verification_reminder_count < _MAX_REMINDERS:
            delay = _REMINDER_DELAYS.get(app.verification_reminder_count)
            already_recent = (
                app.last_verification_reminder_sent_at
                and (now - app.last_verification_reminder_sent_at) < _MIN_GAP_BETWEEN_SENDS
            )
            if delay is not None and elapsed >= delay and not already_recent and app.resume_token:
                reminder_number = app.verification_reminder_count + 1
                fire_and_forget(
                    lambda app=app, reminder_number=reminder_number: send_verification_grace_email(
                        to_email=app.email,
                        full_name=app.full_name,
                        resume_url=_resume_url(app.resume_token),
                        reminder_number=reminder_number,
                        business_name=app.business_name,
                    ),
                    name=f"send_verification_grace_email_{app.id}_{reminder_number}",
                )
                app.verification_reminder_count = reminder_number
                app.last_verification_reminder_sent_at = now
                sent += 1

        # ── Day-7 admin nudge (fires once, regardless of application status —
        # even an already-approved merchant needs this if they never verified) ──
        if (
            app.verification_admin_alert_sent_at is None
            and elapsed >= _REMINDER_DELAYS[_MAX_REMINDERS - 1]
        ):
            from app.infrastructure.alerting.slack import alert

            label = app.business_name or app.full_name or app.email
            fire_and_forget(
                lambda app=app, label=label: alert(
                    title="7-day verification grace period expired",
                    level="warning",
                    detail=(
                        f"*{label}* still hasn't submitted CAC/BVN/NIN, 7+ days after "
                        f"skipping verification (application status: {app.status}). "
                        f"Reminder emails are exhausted. If this should stop them "
                        f"messaging customers, suspend it from the admin dashboard: "
                        f"POST /admin/whatsapp-setup/merchants/{{merchant_id}}/suspend-messaging"
                    ),
                ),
                name=f"verification_grace_admin_alert_{app.id}",
            )
            app.verification_admin_alert_sent_at = now
            alerted += 1

    await db.commit()
    logger.info(
        "Verification grace job: sent=%d alerted=%d scanned=%d", sent, alerted, len(apps)
    )
    return {"sent": sent, "alerted": alerted, "scanned": len(apps)}
