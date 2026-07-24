from num2words import num2words
import logging
logger = logging.getLogger(__name__)


def get_client_ip(request) -> str:
    """
    Real client IP behind Railway's edge (and Cloudflare, once proxied).

    request.client.host alone is NOT the visitor's IP in this setup — it's
    whichever proxy connects directly to the container. Trust order:

      1. CF-Connecting-IP — set by Cloudflare's edge. Cloudflare always
         overwrites this itself, so a client can never forge it once traffic
         is proxied through Cloudflare.
      2. X-Forwarded-For — take the LAST entry only. That's the IP Railway's
         own proxy observed directly. Earlier entries in this header can be
         set by the client itself and are not trustworthy.
      3. request.client.host — direct connection, used only as a last resort
         (e.g. local dev with no proxy in front at all).
    """
    cf_ip = request.headers.get("CF-Connecting-IP")
    if cf_ip:
        return cf_ip.strip()

    xff = request.headers.get("X-Forwarded-For")
    if xff:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            return parts[-1]

    return request.client.host if request.client else "unknown"

def number_to_words(amount: float) -> str:
    # Converts number to words (e.g., 1500 -> "one thousand five hundred")
    # Handles decimals
    whole = int(amount)
    decimals = int(round((amount - whole) * 100))
    words = num2words(whole, lang="en")
    if decimals > 0:
        words += f" and {num2words(decimals)} cents"
    return words
