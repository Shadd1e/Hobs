"""
Slack alerting for critical production events.
Fire-and-forget — never raises, never blocks the main flow.
"""
import os
import logging
import httpx

logger = logging.getLogger(__name__)

SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")

_ICONS = {
    "critical": "🔴",
    "warning":  "🟡",
    "info":     "🟢",
}


async def alert(
    title: str,
    detail: str = "",
    level: str = "critical",
    fields: dict = None,
) -> None:
    """
    Send an alert to #all-ordaa-alerts.
    Safe to call anywhere — swallows all errors so it never
    disrupts the main request flow.
    """
    if not SLACK_WEBHOOK_URL:
        logger.warning("SLACK_WEBHOOK_URL not set — alert suppressed: %s", title)
        return

    icon = _ICONS.get(level, "🔴")
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"{icon} {title}"},
        },
    ]

    if detail:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": detail},
        })

    if fields:
        field_text = "\n".join(f"*{k}:* {v}" for k, v in fields.items())
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": field_text},
        })

    env = os.getenv("RAILWAY_ENVIRONMENT", "unknown")
    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": f"env: `{env}`  |  service: `ordaa-api`"}],
    })

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.post(SLACK_WEBHOOK_URL, json={"blocks": blocks})
            if resp.status_code != 200:
                logger.error("Slack alert failed: %s %s", resp.status_code, resp.text)
    except Exception:
        logger.exception("Slack alert error — suppressed")
