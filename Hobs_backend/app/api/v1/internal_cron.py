# app/api/v1/internal_cron.py
"""
Internal, secret-protected endpoints meant to be hit by a scheduler, not by
users or the frontend. Mirrors the X-Admin-Token pattern used in
admin_whatsapp.py, but with its own secret (CRON_SECRET) since this is a
different trust boundary -- your cron scheduler, not an admin's browser.

Set up once: in Railway, add a Cron Job (Project -> your service -> Cron
Jobs) that runs roughly hourly and does:

    curl -X POST https://<your-api-domain>/internal/cron/onboarding-reminders \
         -H "X-Cron-Secret: $CRON_SECRET"

Or use any external cron service (cron-job.org, GitHub Actions on a
schedule, etc.) -- same header, same URL. Set CRON_SECRET as an env var here
and make it match whatever the scheduler sends.
"""
import logging
import os

from fastapi import APIRouter, Header, HTTPException

from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal/cron", tags=["Internal Cron"])


def _check_cron_secret(x_cron_secret: str):
    expected = os.getenv("CRON_SECRET", "")
    if not expected:
        raise HTTPException(status_code=503, detail="CRON_SECRET not configured.")
    if x_cron_secret != expected:
        raise HTTPException(status_code=401, detail="Invalid cron secret.")


@router.post("/onboarding-reminders")
async def run_onboarding_reminders(x_cron_secret: str = Header(default="")):
    _check_cron_secret(x_cron_secret)

    from app.api.v1.workers.reminder_job import send_draft_reminders

    async with AsyncSessionLocal() as db:
        result = await send_draft_reminders(db)
    return result
