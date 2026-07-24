# app/api/v1/workers/background_tasks.py
"""
Background task utilities.

fire_and_forget(coro, name=...)
    Wraps any coroutine in an asyncio.Task with automatic exponential-backoff
    retry (INF-4).  Failures are logged to the structured error channel so
    dropped verification emails and Slack alerts are visible in production.

    Retry schedule: 2 s → 4 s → 8 s  (3 attempts total, ~14 s max wait)
    After all retries are exhausted the failure is logged at ERROR level
    with the task name and exception, giving an actionable signal to alert on.
"""

import asyncio
import logging

logger = logging.getLogger(__name__)

_MAX_RETRIES   = 3
_BASE_DELAY    = 2.0   # seconds — doubles on each retry (2 → 4 → 8)


async def _run_with_retry(coro_factory, name: str):
    """Execute coro_factory() up to _MAX_RETRIES times with exponential backoff."""
    delay = _BASE_DELAY
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            await coro_factory()
            if attempt > 1:
                logger.info("Background task '%s' succeeded on attempt %d", name, attempt)
            return
        except Exception as exc:
            if attempt < _MAX_RETRIES:
                logger.warning(
                    "Background task '%s' failed (attempt %d/%d) — retrying in %.0fs: %s",
                    name, attempt, _MAX_RETRIES, delay, exc,
                )
                await asyncio.sleep(delay)
                delay *= 2
            else:
                logger.error(
                    "Background task '%s' failed after %d attempts — giving up: %s",
                    name, _MAX_RETRIES, exc,
                    exc_info=True,
                )


def fire_and_forget(coro_or_factory, *, name: str = "background_task"):
    """
    Schedule a fire-and-forget asyncio task, with exponential-backoff retry
    (2s -> 4s -> 8s, 3 attempts total) when possible.

    Two calling conventions are supported:

    1. Zero-arg factory (PREFERRED — gets real retries):
        fire_and_forget(lambda: send_verification_email(...), name="...")
       A lambda can be called again on each retry attempt, since each call
       produces a fresh coroutine. This is the only way to get the retry
       behavior described above.

    2. Bare coroutine (legacy — single attempt only, no retry):
        fire_and_forget(send_verification_email(...), name="...")
       A coroutine object can only be awaited once, so if it fails there is
       nothing to retry — this form gets one attempt with clean error
       logging, same as before. Prefer form 1 for anything where a dropped
       send actually matters (verification/welcome/reminder emails, etc).
    """
    if asyncio.iscoroutine(coro_or_factory):
        coro = coro_or_factory

        async def _once():
            try:
                await coro
            except Exception:
                logger.error(
                    "Background task '%s' failed (single attempt — passed as a bare "
                    "coroutine, so it can't be retried; pass a lambda for retries): ",
                    name, exc_info=True,
                )

        asyncio.create_task(_once(), name=name)
    else:
        # It's a zero-arg callable factory — safe to call again on retry.
        asyncio.create_task(_run_with_retry(coro_or_factory, name), name=name)
