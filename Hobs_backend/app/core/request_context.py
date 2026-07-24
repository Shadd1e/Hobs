# app/core/request_context.py
"""
Request correlation context (INF-5).

A single ContextVar that carries a request_id through the full async
call stack for a given request: webhook → handler → orchestrator → service → DB.

Usage
-----
Set at the entry point (webhook):
    from app.core.request_context import request_id_var
    request_id_var.set(str(uuid4())[:8])

Read anywhere downstream (e.g. in a service or orchestrator log call):
    from app.core.request_context import get_request_id
    logger.info("Processing cart: %s", cart_id, extra={"request_id": get_request_id()})

The CorrelationFilter below injects request_id into every log record
automatically so you don't need to pass it manually to every log call.
Add it to your logging config's filters list.
"""

import logging
from contextvars import ContextVar

# The ContextVar — asyncio-safe, task-local (each request gets its own copy).
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


def get_request_id() -> str:
    return request_id_var.get()


class CorrelationFilter(logging.Filter):
    """
    Logging filter that injects the current request_id into every log record.
    Attach to any handler to get request_id in every log line automatically.
    """
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True
