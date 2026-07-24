# app/core/redis_client.py

import hashlib
import logging
import json
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as redis


def _hash_phone(phone: str) -> str:
    """Hash a phone number for use as a cache key component.
    Deterministic but irreversible — prevents PII exposure in Redis key listings."""
    return hashlib.sha256(phone.encode()).hexdigest()[:16]

from app.core.config import settings
from app.core.helpers import get_client_ip

logger = logging.getLogger(__name__)

WAMID_TTL   = 86400       # 24 hours — matches Meta's maximum webhook retry window
LOCK_TTL    = 30          # seconds — per-user processing lock
SESSION_TTL = 7200        # 2 hours — conversation session


# ==================================================
# SINGLE REDIS CLIENT (SHARED)
# ==================================================

class RedisService:
    """Single source of truth for Redis connection."""

    def __init__(self):
        self._client: Optional[redis.Redis] = None

    async def get_client(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_keepalive=True,
                health_check_interval=30,
                max_connections=50,  # INF-1: cap pool to prevent fd exhaustion under load
            )
            await self._client.ping()
            logger.info("✅ Redis client initialized")

        return self._client


redis_service = RedisService()


# ==================================================
# KEY NAMESPACES
# ==================================================

class Keys:
    @staticmethod
    def history(client_id: str, user_id: str) -> str:
        # IMPORTANT: keyed by client_id (store ID), not merchant_id.
        # ConversationMemory writes history with client_id as the namespace.
        # whatsapp_handler must read with client_id to match.
        return f"session:history:{client_id}:{_hash_phone(user_id)}"

    @staticmethod
    def wamid(wamid: str) -> str:
        return f"session:wamid:{wamid}"

    @staticmethod
    def lock(merchant_id: str, user_phone: str) -> str:
        return f"session:lock:{merchant_id}:{_hash_phone(user_phone)}"

    @staticmethod
    def tenant(phone_number_id: str) -> str:
        return f"session:tenant:{phone_number_id}"

    @staticmethod
    def session_flow(client_id: str, user_id: str) -> str:
        return f"session:flow:{client_id}:{_hash_phone(user_id)}"


# ==================================================
# WAMID DEDUP (ONLY PLACE DEDUPE SHOULD EXIST)
# ==================================================

async def seen_wamid(wamid: str) -> bool:
    """
    Atomic WhatsApp message deduplication.

    Returns True if this is a NEW message (not seen before).
    Returns False if it's a duplicate.

    Uses SET NX (only set if not exists) for atomicity.
    """
    try:
        client = await redis_service.get_client()
        key = Keys.wamid(wamid)

        # SET key value NX EX ttl — returns True only if key was newly set
        result = await client.set(key, "1", nx=True, ex=WAMID_TTL)
        return result is True  # True = new, None = already existed

    except Exception as e:
        logger.exception(f"Redis WAMID dedup failed: {e}")
        return True  # fail open — better to process a duplicate than drop a message


# ==================================================
# USER LOCK (PER-USER SERIALISATION)
# ==================================================

async def acquire_user_lock(
    merchant_id: str,
    user_phone: str,
    lock_value: str,
) -> bool:
    """
    Acquire a per-user processing lock.
    Returns True if lock acquired, False if already locked.
    """
    try:
        client = await redis_service.get_client()
        key = Keys.lock(merchant_id, user_phone)
        return bool(await client.set(key, lock_value, nx=True, ex=LOCK_TTL))

    except Exception as e:
        logger.exception(f"Redis lock acquire failed: {e}")
        return True  # fail open


async def release_user_lock(
    merchant_id: str,
    user_phone: str,
    lock_value: str,
) -> None:
    """
    Release the per-user lock — only if we own it.
    Uses a Lua script for atomic check-and-delete.
    """
    try:
        client = await redis_service.get_client()
        key = Keys.lock(merchant_id, user_phone)

        lua = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
        """
        await client.eval(lua, 1, key, lock_value)

    except Exception as e:
        logger.exception(f"Redis lock release failed: {e}")


# ==================================================
# TENANT CACHE
# ==================================================

async def cache_tenant(phone_number_id: str, tenant_data: dict, ttl: int = 86400):
    try:
        client = await redis_service.get_client()
        key = Keys.tenant(phone_number_id)
        await client.setex(key, ttl, json.dumps(tenant_data))
    except Exception as e:
        logger.exception(f"Redis cache_tenant failed: {e}")


async def get_cached_tenant(phone_number_id: str) -> Optional[dict]:
    try:
        client = await redis_service.get_client()
        key = Keys.tenant(phone_number_id)
        data = await client.get(key)
        return json.loads(data) if data else None
    except Exception as e:
        logger.exception(f"Redis get_cached_tenant failed: {e}")
        return None


# ==================================================
# SESSION MANAGEMENT
# ==================================================

async def get_session(client_id: str, user_id: str) -> dict:
    try:
        client = await redis_service.get_client()
        key = Keys.session_flow(client_id, user_id)

        async with client.pipeline(transaction=False) as pipe:
            pipe.get(key)
            pipe.expire(key, SESSION_TTL)   # INF-3: sliding window — reset TTL on every read
            results = await pipe.execute()

        data = results[0]
        return json.loads(data) if data else {}

    except Exception as e:
        logger.error(f"Redis get_session failed: {e}")
        return {}


async def set_session(
    client_id: str,
    user_id: str,
    data: dict,
    ttl: int = SESSION_TTL
):
    try:
        client = await redis_service.get_client()
        key = Keys.session_flow(client_id, user_id)

        await client.setex(key, ttl, json.dumps(data))

    except Exception as e:
        logger.error(f"Redis set_session failed: {e}")


async def delete_session(client_id: str, user_id: str):
    try:
        client = await redis_service.get_client()
        key = Keys.session_flow(client_id, user_id)

        await client.delete(key)

    except Exception as e:
        logger.error(f"Redis delete_session failed: {e}")


# ==================================================
# CHAT HISTORY
# ==================================================

async def add_to_history(
    client_id: str,
    user_id: str,
    role: str,
    content: str,
):
    try:
        client = await redis_service.get_client()
        key = Keys.history(client_id, user_id)

        message = json.dumps({
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

        async with client.pipeline(transaction=True) as pipe:
            pipe.lpush(key, message)
            pipe.ltrim(key, 0, 19)        # keep last 20 messages
            pipe.expire(key, SESSION_TTL)  # consistent with session TTL
            await pipe.execute()

    except Exception as e:
        logger.error(f"Redis add_to_history failed: {e}")


async def get_history(client_id: str, user_id: str) -> list:
    """Read conversation history (newest-first). Keyed by client_id to match ConversationMemory writes."""
    try:
        client = await redis_service.get_client()
        key = Keys.history(client_id, user_id)

        items = await client.lrange(key, 0, -1)
        return [json.loads(i) for i in items]

    except Exception as e:
        logger.error(f"Redis get_history failed: {e}")
        return []


async def delete_history(client_id: str, user_id: str) -> None:
    """
    Delete all conversation history for a user.
    Called by ConversationMemory.clear() so a fresh start truly resets context.
    """
    try:
        client = await redis_service.get_client()
        key = Keys.history(client_id, user_id)
        await client.delete(key)
    except Exception as e:
        logger.error(f"Redis delete_history failed: {e}")


async def invalidate_tenant_cache(phone_number_id: str) -> None:
    """
    Delete the cached TenantContext for a given WhatsApp phone_number_id.
    Call this after changing delivery settings or assistant persona so the
    next inbound message fetches fresh config from the DB.
    Fails silently — cache miss is handled gracefully by the resolver.
    """
    try:
        client = await redis_service.get_client()
        key    = Keys.tenant(phone_number_id)
        await client.delete(key)
        logger.debug("Tenant cache invalidated for phone_number_id=%s", phone_number_id)
    except Exception as e:
        logger.warning("invalidate_tenant_cache failed (non-fatal): %s", e)


# Backwards-compatibility alias used by tenant_resolver.py
set_cached_tenant = cache_tenant


# ==================================================
# ADMIN SESSION STORE  (Redis-backed, survives restarts)
# ==================================================

ADMIN_SESSION_TTL    = 4 * 3600   # 4 hours
ADMIN_RATE_LIMIT_TTL = 300         # 5-minute window for brute-force check
ADMIN_RATE_LIMIT_MAX = 5           # max attempts per window


async def create_admin_session(token: str) -> None:
    """Store an admin session token in Redis with a 4-hour TTL."""
    try:
        client = await redis_service.get_client()
        await client.setex(f"admin:session:{token}", ADMIN_SESSION_TTL, "1")
    except Exception as e:
        logger.error("create_admin_session failed: %s", e)
        raise


async def validate_admin_session(token: str) -> bool:
    """Return True if the token exists in Redis (i.e. is a live session)."""
    try:
        client = await redis_service.get_client()
        return bool(await client.get(f"admin:session:{token}"))
    except Exception as e:
        logger.error("validate_admin_session failed: %s", e)
        return False


async def delete_admin_session(token: str) -> None:
    try:
        client = await redis_service.get_client()
        await client.delete(f"admin:session:{token}")
    except Exception as e:
        logger.warning("delete_admin_session failed (non-fatal): %s", e)


async def check_admin_rate_limit(ip: str) -> bool:
    """
    Sliding-window rate limit for admin login attempts.
    Returns True if the request is allowed, False if the IP is over the limit.
    """
    try:
        client = await redis_service.get_client()
        key = f"admin:ratelimit:{ip}"
        count = await client.incr(key)
        if count == 1:
            await client.expire(key, ADMIN_RATE_LIMIT_TTL)
        return count <= ADMIN_RATE_LIMIT_MAX
    except Exception as e:
        logger.warning("check_admin_rate_limit failed, allowing request: %s", e)
        return True  # fail open — don't lock out admin if Redis blips


# ==================================================
# PUBLIC APPLY-FORM RATE LIMIT
# Prevents the public "Apply to Use" endpoint (and the linked
# add-WhatsApp-number page) from being spammed/flooded.
# Limit: 3 submissions per IP per hour.
# ==================================================

APPLY_RATE_LIMIT_TTL = 3600   # 1 hour
APPLY_RATE_LIMIT_MAX = 3       # max submissions per IP per window


async def check_apply_rate_limit(ip: str) -> bool:
    """
    Sliding-window rate limit for POST /merchants/apply.
    Returns True if the request is allowed, False if the IP is over the limit.
    """
    try:
        client = await redis_service.get_client()
        key = f"apply:ratelimit:{ip}"
        count = await client.incr(key)
        if count == 1:
            await client.expire(key, APPLY_RATE_LIMIT_TTL)
        return count <= APPLY_RATE_LIMIT_MAX
    except Exception as e:
        logger.warning("check_apply_rate_limit failed, allowing request: %s", e)
        return True  # fail open — don't block real applicants if Redis blips


# ==================================================
# MERCHANT / STORE LOGIN RATE LIMIT
# Protects POST /merchants/login, POST /clients/login,
# and POST /merchants/forgot-password from brute-force
# and email-bombing attacks.
#
# Keyed on IP + identifier (email or store ID) so:
#   - One IP can't hammer a single account.
#   - One account can't be targeted from many IPs
#     without each IP also hitting its own limit.
#
# Thresholds are intentionally more generous than the
# admin limit (5/5min) because real merchants mistype
# passwords and we don't want to lock them out.
# ==================================================

LOGIN_RATE_LIMIT_TTL = 900   # 15-minute window
LOGIN_RATE_LIMIT_MAX = 10    # max attempts per IP+identifier per window


async def check_login_rate_limit(ip: str, identifier: str) -> bool:
    """
    Sliding-window rate limit for public login and password-reset endpoints.

    Args:
        ip:         The client's IP address.
        identifier: The account being targeted — email for merchant login
                    and forgot-password, client_id for store login.

    Returns True if the request is allowed, False if the limit is exceeded.
    Fails open (returns True) if Redis is unavailable so a Redis blip
    never locks out real users.
    """
    try:
        client = await redis_service.get_client()
        # Hash the identifier so email addresses don't appear in Redis key listings
        id_hash = hashlib.sha256(identifier.lower().encode()).hexdigest()[:16]
        key     = f"login:ratelimit:{ip}:{id_hash}"
        count   = await client.incr(key)
        if count == 1:
            await client.expire(key, LOGIN_RATE_LIMIT_TTL)
        return count <= LOGIN_RATE_LIMIT_MAX
    except Exception as e:
        logger.warning("check_login_rate_limit failed, allowing request: %s", e)
        return True  # fail open


# ==================================================
# WHATSAPP OUTBOUND RATE LIMIT
# Prevents bot loops and accidental message storms.
# Limit: 30 outbound messages per user per 10 minutes.
# ==================================================

WHATSAPP_RATE_LIMIT_MAX = 30
WHATSAPP_RATE_LIMIT_TTL = 600  # 10 minutes


async def check_whatsapp_rate_limit(to_number: str) -> bool:
    """
    Returns True if the message is allowed, False if the user is over-limit.
    Fails open — if Redis is unavailable we always allow.
    """
    try:
        client = await redis_service.get_client()
        key = f"wa:ratelimit:{to_number}"
        count = await client.incr(key)
        if count == 1:
            await client.expire(key, WHATSAPP_RATE_LIMIT_TTL)
        return count <= WHATSAPP_RATE_LIMIT_MAX
    except Exception as e:
        logger.warning("check_whatsapp_rate_limit failed, allowing: %s", e)
        return True


# ==================================================
# GENERAL-PURPOSE RATE LIMIT
# A reusable fixed-window limiter for any endpoint that doesn't already
# have its own dedicated limiter above. Same fail-open pattern as the
# rest of this file — a Redis blip should never lock out real users.
# ==================================================

async def check_rate_limit(key: str, max_requests: int, window_seconds: int) -> bool:
    """
    Returns True if the request is allowed, False if `key` is over-limit
    for the current fixed window.
    """
    try:
        client = await redis_service.get_client()
        rkey = f"ratelimit:{key}"
        count = await client.incr(rkey)
        if count == 1:
            await client.expire(rkey, window_seconds)
        return count <= max_requests
    except Exception as e:
        logger.warning("check_rate_limit failed for key=%s, allowing request: %s", key, e)
        return True  # fail open


def rate_limiter(prefix: str, max_requests: int, window_seconds: int):
    """
    FastAPI dependency factory. Drop this on any route to rate-limit it,
    keyed by the authenticated merchant_id when present, falling back to
    client IP for unauthenticated routes.

    Usage:
        @router.post("/some-route", dependencies=[Depends(
            rate_limiter("some-route", max_requests=10, window_seconds=600)
        )])
    """
    async def _dependency(request):
        from fastapi import HTTPException, Request  # noqa: F401 — Request import kept for clarity

        identifier = getattr(request.state, "merchant_id", None)
        if not identifier:
            identifier = get_client_ip(request)

        allowed = await check_rate_limit(f"{prefix}:{identifier}", max_requests, window_seconds)
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="Too many requests. Please try again shortly.",
            )

    # Annotate after definition so FastAPI's dependency-injection introspection
    # sees `request: Request` and injects the real object — an unannotated
    # `request` parameter would otherwise be treated as a query parameter.
    from fastapi import Request as _Request
    _dependency.__annotations__["request"] = _Request

    return _dependency


# ==================================================
# WEBHOOK SIGNATURE-MISMATCH ALERT COOLDOWN
# A garbage POST to /webhook/whatsapp doesn't need a valid signature to
# reach the handler — only to pass verification. Without this, anyone can
# spam the endpoint with junk and trigger one Slack alert per request,
# burying real alerts and risking Slack's own rate limits. This caps it
# to at most one alert per cooldown window, regardless of how many
# invalid requests arrive in that window.
# ==================================================

WEBHOOK_ALERT_COOLDOWN_TTL = 300  # 5 minutes


async def should_send_webhook_alert() -> bool:
    """
    Returns True the first time this is called in a 5-minute window (and
    sets the cooldown), False for every call after that until it expires.
    Fails open — if Redis is unavailable, always alert (better a noisy
    Slack channel than a missed real incident during an outage).
    """
    try:
        client = await redis_service.get_client()
        key = "webhook:sig_mismatch:cooldown"
        # SET ... NX only succeeds if the key doesn't already exist —
        # that's the "first one in the window" signal.
        was_set = await client.set(key, "1", nx=True, ex=WEBHOOK_ALERT_COOLDOWN_TTL)
        return bool(was_set)
    except Exception as e:
        logger.warning("should_send_webhook_alert failed, allowing alert: %s", e)
        return True