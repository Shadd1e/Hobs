# app/services/customer_context.py
"""
CustomerContextService — two responsibilities:

1. Redis short-term session data (last_product, etc.) — unchanged from before.
2. CustomerProfile DB upsert — creates/updates the cross-store identity record
   on every inbound message, and exposes helpers for first-time detection and
   name storage.

Design notes:
- DB operations require a live AsyncSession to be passed in.
- Redis operations are self-contained (no session needed).
- All failures are swallowed and logged — this must never crash the main flow.
"""

import json
import logging
from typing import Optional, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone

from app.core.redis_client import redis_service  # ARC-2: use shared pool, not a private client

logger = logging.getLogger(__name__)

TTL_SECONDS  = 20 * 60  # 20 minutes


class CustomerContextService:

    def __init__(self):
        # ARC-2: no private Redis client — all operations go through the shared
        # redis_service singleton to avoid a second connection pool.
        pass

    # ── Redis key helpers ──────────────────────────────────────────────────────

    def _key(self, merchant_id: str, client_id: str, user_id: str) -> str:
        return f"ctx:{merchant_id}:{client_id}:{user_id}"

    # ── Redis: last product ────────────────────────────────────────────────────

    async def set_last_product(
        self,
        *,
        merchant_id: str,
        client_id: str,
        user_id: str,
        product_id: str,
        price: float,
    ) -> None:
        try:
            client = await redis_service.get_client()
            await client.setex(
                self._key(merchant_id, client_id, user_id),
                TTL_SECONDS,
                json.dumps({"product_id": product_id, "price": price}),
            )
        except Exception:
            logger.exception("Redis set_last_product failed")

    async def get_last_product(
        self,
        *,
        merchant_id: str,
        client_id: str,
        user_id: str,
    ) -> Optional[Dict[str, Any]]:
        try:
            client = await redis_service.get_client()
            raw = await client.get(self._key(merchant_id, client_id, user_id))
            return json.loads(raw) if raw else None
        except Exception:
            logger.exception("Redis get_last_product failed")
            return None

    async def clear(self, merchant_id: str, client_id: str, user_id: str) -> None:
        try:
            client = await redis_service.get_client()
            await client.delete(self._key(merchant_id, client_id, user_id))
        except Exception:
            logger.exception("Redis clear failed")

    # ── DB: CustomerProfile upsert ─────────────────────────────────────────────

    async def touch_profile(
        self,
        *,
        db: AsyncSession,
        phone_number: str,
    ) -> tuple:  # (Optional["CustomerProfile"], bool)
        """
        Ensure a CustomerProfile row exists for this phone number and update
        last_seen_at. Creates the record on first contact.

        Returns a tuple of (profile, is_new):
          - profile: the profile object (with .name possibly None if not yet
            given), or None on failure.
          - is_new: True only when this call created the row, i.e. this is
            this phone number's very first message to ANY store on the
            platform. Callers can use this as the true onboarding signal
            (distinct from CustomerContextService.is_first_time(), which
            stays True until a name is captured for welcome-message gating).

        Never raises — returns (None, False) on failure.
        """
        from app.models.customer_profile import CustomerProfile

        try:
            result = await db.execute(
                select(CustomerProfile).where(
                    CustomerProfile.phone_number == phone_number
                )
            )
            profile = result.scalar_one_or_none()

            now = datetime.now(timezone.utc)
            is_new = profile is None

            if profile is None:
                profile = CustomerProfile(
                    phone_number=phone_number,
                    name=None,
                    created_at=now,
                    last_seen_at=now,
                )
                db.add(profile)
                logger.info("New customer profile created: %s", phone_number)
            else:
                profile.last_seen_at = now

            await db.flush()
            return profile, is_new

        except Exception:
            logger.exception("touch_profile failed for %s", phone_number)
            return None, False

    async def get_profile(
        self,
        *,
        db: AsyncSession,
        phone_number: str,
    ) -> Optional["CustomerProfile"]:  # type: ignore[name-defined]
        """Fetch profile without updating last_seen_at. Returns None if not found."""
        from app.models.customer_profile import CustomerProfile
        try:
            result = await db.execute(
                select(CustomerProfile).where(
                    CustomerProfile.phone_number == phone_number
                )
            )
            return result.scalar_one_or_none()
        except Exception:
            logger.exception("get_profile failed for %s", phone_number)
            return None

    async def save_name(
        self,
        *,
        db: AsyncSession,
        phone_number: str,
        name: str,
    ) -> None:
        """
        Persist the customer's name on their profile.
        Also syncs it to ConversationMemory so the session has it in Redis too.
        """
        from app.models.customer_profile import CustomerProfile
        try:
            result = await db.execute(
                select(CustomerProfile).where(
                    CustomerProfile.phone_number == phone_number
                )
            )
            profile = result.scalar_one_or_none()
            if profile:
                profile.name = name.strip()
                await db.flush()
                logger.info("Name saved for %s: %s", phone_number, name)
        except Exception:
            logger.exception("save_name failed for %s", phone_number)

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def is_first_time(profile: Optional[Any]) -> bool:
        """
        True if this customer has never contacted us before (profile just created
        with no name), or profile lookup failed.

        We treat a freshly-created, nameless profile as first-time so they
        get the welcome message and name prompt.
        """
        if profile is None:
            return True
        return not profile.is_named
