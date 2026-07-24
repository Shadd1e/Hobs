# app/services/whatsapp_sender.py

import os
import logging
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from typing import Optional, Dict, Any, List, Union

logger = logging.getLogger(__name__)

META_GRAPH_VERSION = "v21.0"
META_SYSTEM_TOKEN = os.getenv("META_SYSTEM_TOKEN")


class HTTPClientPool:
    _instance = None
    _client = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    async def get_client(self):
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30)
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None


http_pool = HTTPClientPool()


def _get_token() -> str:
    token = os.getenv("META_SYSTEM_TOKEN") or META_SYSTEM_TOKEN
    if not token:
        raise RuntimeError("META_SYSTEM_TOKEN is not set")
    return token


# ==================================================
# TYPING INDICATOR  (UX-1)
# ==================================================

async def send_typing_indicator(*, to_number: str, phone_number_id: str) -> None:
    """
    Send a WhatsApp typing indicator (mark-as-typing) before processing begins.

    This tells the customer the bot is working — on a congested Nigerian mobile
    connection, 2-5 seconds of silence feels like a crash.  Callers should fire
    this immediately on message receipt, before any DB/LLM work starts.

    Fails silently — a missing indicator is far less bad than blocking the flow.
    """
    try:
        token     = _get_token()
        to_norm   = _normalise_number(to_number)
        url       = f"https://graph.facebook.com/{META_GRAPH_VERSION}/{phone_number_id}/messages"
        client    = await http_pool.get_client()

        await client.post(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type":  "application/json",
            },
            json={
                "messaging_product": "whatsapp",
                "recipient_type":    "individual",
                "to":               to_norm,
                "type":             "reaction",
                # Meta typing indicator — status "typing" is the documented value
                "status": "typing",
            },
        )
    except Exception as _e:
        logger.debug("Typing indicator failed (non-fatal): %s", _e)


def _normalise_number(number: str) -> str:
    """Ensure E.164 format with + prefix."""
    return "+" + number.lstrip("+").strip()


# ==================================================
# TEXT MESSAGE
# ==================================================

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError))
)
async def send_whatsapp_message(*, to_number: str, message: str, phone_number_id: str):
    """Send a plain-text WhatsApp message."""
    from app.core.redis_client import check_whatsapp_rate_limit
    if not await check_whatsapp_rate_limit(to_number):
        logger.warning("WhatsApp rate limit exceeded for %s — message dropped", to_number)
        return

    # Meta rejects messages over 4096 characters with a hard 400 error.
    # Truncate here so callers never have to worry about it, and we always
    # deliver something rather than silently dropping the whole message.
    _META_MAX = 4096
    if len(message) > _META_MAX:
        logger.warning(
            "Message to %s truncated from %d to %d chars",
            to_number, len(message), _META_MAX,
        )
        message = message[: _META_MAX - 3] + "..."

    token = _get_token()
    to_number = _normalise_number(to_number)

    url = f"https://graph.facebook.com/{META_GRAPH_VERSION}/{phone_number_id}/messages"
    client = await http_pool.get_client()

    resp = await client.post(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_number,
            "type": "text",
            "text": {"body": message},
        },
    )

    if resp.status_code not in (200, 201):
        logger.error("Meta send failed: %s - %s", resp.status_code, resp.text)


# ==================================================
# IMAGE MESSAGE
# ==================================================

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError))
)
async def send_whatsapp_image(
    *,
    to_number: str,
    image_url: str,
    caption: Optional[str] = None,
    phone_number_id: str,
):
    """
    Send a product image via WhatsApp.

    image_url must be a publicly accessible direct image link.
    caption is optional — used for the product name/price summary.
    """
    from typing import Optional  # local import to keep module-level clean
    token = _get_token()
    to_number = _normalise_number(to_number)

    url = f"https://graph.facebook.com/{META_GRAPH_VERSION}/{phone_number_id}/messages"
    client = await http_pool.get_client()

    image_block: dict = {"link": image_url}
    if caption:
        image_block["caption"] = caption

    resp = await client.post(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_number,
            "type": "image",
            "image": image_block,
        },
    )

    if resp.status_code not in (200, 201):
        logger.error(
            "Meta image send failed: %s - %s", resp.status_code, resp.text
        )
