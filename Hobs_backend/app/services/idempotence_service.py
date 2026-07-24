# app/services/idempotence_service.py

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, Tuple

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.idempotence import IdempotencyKey

logger = logging.getLogger(__name__)


# =====================================================
# EXCEPTIONS
# =====================================================

class IdempotencyError(Exception):
    pass


class IdempotencyKeyExistsError(IdempotencyError):
    pass


class IdempotencyHashMismatchError(IdempotencyError):
    pass


# =====================================================
# SERVICE
# =====================================================

class IdempotenceService:
    """
    Production-grade idempotency service.

    IMPORTANT:
    - This service does NOT manage transactions.
    - The caller MUST commit / rollback.
    - This service assumes clean transaction boundaries.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    # =====================================================
    # GET OR CREATE (Atomic)
    # =====================================================

    async def get_or_create(
        self,
        key: str,
        request_hash: str,
        merchant_id: str,
        ttl_minutes: int = 60,
    ) -> Tuple[IdempotencyKey, bool]:
        """
        Returns:
            (record, created_bool)

        created_bool:
            True  -> New key created
            False -> Existing key returned
        """

        now = self._now()
        expires_at = now + timedelta(minutes=ttl_minutes)

        # Try insert first (atomic upsert)
        stmt = (
            pg_insert(IdempotencyKey)
            .values(
                merchant_id=merchant_id,
                key=key,
                request_hash=request_hash,
                expires_at=expires_at,
                is_processing=False,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(
                index_elements=["merchant_id", "key"]
            )
            .returning(IdempotencyKey)
        )

        result = await self.db.execute(stmt)
        record = result.scalar_one_or_none()

        if record:
            return record, True

        # If not created, fetch existing row with lock
        result = await self.db.execute(
            select(IdempotencyKey)
            .where(
                IdempotencyKey.merchant_id == merchant_id,
                IdempotencyKey.key == key,
            )
            .with_for_update()
        )

        record = result.scalar_one()

        # Check expiration
        if record.expires_at <= now:
            # Expired → treat as reusable
            record.request_hash = request_hash
            record.expires_at = expires_at
            record.response_data = None
            record.response_status = None
            record.response_headers = None
            record.is_processing = False
            record.completed_at = None
            record.updated_at = now
            await self.db.flush()
            return record, False

        # Validate request hash consistency
        if record.request_hash != request_hash:
            raise IdempotencyHashMismatchError(
                "Request hash does not match existing idempotency key."
            )

        return record, False

    # =====================================================
    # MARK AS PROCESSING
    # =====================================================

    async def mark_as_processing(self, record: IdempotencyKey) -> None:
        """
        Marks record as processing.
        Raises if already processing or completed.
        """

        if record.response_data is not None:
            raise IdempotencyError("RESPONSE_ALREADY_EXISTS")

        if record.is_processing:
            raise IdempotencyError("CHECKOUT_IN_PROGRESS")

        record.is_processing = True
        record.updated_at = self._now()
        await self.db.flush()

    # =====================================================
    # SAVE RESPONSE
    # =====================================================

    async def save_response(
        self,
        record: IdempotencyKey,
        response_data: Dict[str, Any],
        response_status: int,
        response_headers: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Saves successful response and marks processing complete.
        """

        if record.response_data is not None:
            raise IdempotencyKeyExistsError("Response already saved.")

        now = self._now()

        record.response_data = response_data
        record.response_status = int(response_status)
        record.response_headers = response_headers or {}
        record.is_processing = False
        record.completed_at = now
        record.updated_at = now

        await self.db.flush()

    # =====================================================
    # GET CACHED RESPONSE
    # =====================================================

    async def get_response(
        self,
        key: str,
        merchant_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Returns cached response if exists.
        """

        result = await self.db.execute(
            select(IdempotencyKey).where(
                IdempotencyKey.merchant_id == merchant_id,
                IdempotencyKey.key == key,
                IdempotencyKey.expires_at > self._now(),
            )
        )

        record = result.scalar_one_or_none()

        if not record or record.response_data is None:
            return None

        return {
            "data": record.response_data,
            "status": record.response_status,
            "headers": record.response_headers or {},
        }

    # =====================================================
    # RESET PROCESSING (Failure Recovery)
    # =====================================================

    async def reset_processing(self, record: IdempotencyKey) -> None:
        """
        Clears processing flag (used after failure).
        """
        record.is_processing = False
        record.updated_at = self._now()
        await self.db.flush()

    # =====================================================
    # CLEANUP EXPIRED
    # =====================================================

    async def cleanup_expired(self) -> int:
        """
        Deletes expired idempotency records.
        """

        now = self._now()

        result = await self.db.execute(
            delete(IdempotencyKey).where(
                IdempotencyKey.expires_at <= now
            )
        )

        deleted = result.rowcount or 0
        logger.info(f"Cleaned {deleted} expired idempotency records")

        return deleted