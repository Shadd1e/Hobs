# app/conversation/store_hours.py
"""
Utility for checking whether a store is currently within its opening hours.
"""

import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


def is_store_open(
    opens_at: Optional[str],
    closes_at: Optional[str],
    timezone_str: str = "Africa/Lagos",
) -> bool:
    """
    Return True if the store is currently open.

    Args:
        opens_at:     Opening time as "HH:MM" (24hr). None = always open.
        closes_at:    Closing time as "HH:MM" (24hr). None = always open.
        timezone_str: IANA timezone string (e.g. "Africa/Lagos").

    Handles overnight hours: if opens_at > closes_at the store spans midnight
    (e.g. opens 22:00, closes 06:00).
    """
    if not opens_at or not closes_at:
        return True  # No hours configured → always open

    try:
        try:
            from zoneinfo import ZoneInfo  # Python 3.9+
            tz = ZoneInfo(timezone_str)
        except ImportError:
            import pytz
            tz = pytz.timezone(timezone_str)

        now     = datetime.now(tz)
        current = now.strftime("%H:%M")

        if opens_at <= closes_at:
            # Normal hours: e.g. 09:00 – 21:00
            return opens_at <= current <= closes_at
        else:
            # Overnight hours: e.g. 22:00 – 06:00
            return current >= opens_at or current <= closes_at

    except Exception as e:
        logger.warning("store_hours check failed (%s) — defaulting to open", e)
        return True  # Fail open so we never accidentally block customers
