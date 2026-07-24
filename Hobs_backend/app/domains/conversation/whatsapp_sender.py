# app/domains/conversation/whatsapp_sender.py

import os
import logging
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger(__name__)

META_GRAPH_VERSION = "v21.0"


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


class MetaServerError(Exception):
    """Raised on Meta 5xx so tenacity will retry."""
    pass


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError, MetaServerError)),
    reraise=True,
)
async def send_whatsapp_message(*, to_number: str, message: str, phone_number_id: str) -> bool:
    """
    Send a WhatsApp message via Meta Graph API.
    Retries up to 3 times on network errors or Meta 5xx responses.
    Returns True on success, raises on final failure.
    """
    token = os.getenv("META_SYSTEM_TOKEN")
    if not token:
        logger.error("META_SYSTEM_TOKEN not set — cannot send WhatsApp message")
        return False

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

    if resp.status_code in (200, 201):
        return True

    if resp.status_code >= 500:
        # Transient Meta error — tenacity will retry
        raise MetaServerError(f"Meta {resp.status_code}: {resp.text[:200]}")

    # 4xx = permanent failure (bad number, blocked, etc.) — log and don't retry
    logger.error(
        "Meta send failed (permanent)",
        extra={
            "status_code": resp.status_code,
            "to_number": to_number,
            "response": resp.text[:500],
        },
    )
    return False
