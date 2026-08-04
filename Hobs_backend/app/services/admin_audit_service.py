# app/services/admin_audit_service.py
import hashlib
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin_action_log import AdminActionLog


def _session_fingerprint(token: str) -> str:
    """Non-reversible, truncated — enough to tell sessions apart without
    storing the actual admin credential in a log table."""
    if not token:
        return "unknown"
    return hashlib.sha256(token.encode()).hexdigest()[:16]


async def log_admin_action(
    db: AsyncSession,
    *,
    request: Request,
    action: str,
    target_type: str,
    target_id: str,
    detail: str = None,
) -> None:
    """
    Write one append-only audit row. Call this in the SAME transaction as
    the mutation it's describing (i.e. before db.commit()) so the log entry
    and the action it records are atomic — either both land or neither does.
    """
    token = request.headers.get("X-Admin-Token", "")
    entry = AdminActionLog(
        actor_session_id=_session_fingerprint(token),
        ip_address=request.client.host if request.client else None,
        action=action,
        target_type=target_type,
        target_id=str(target_id),
        detail=detail,
    )
    db.add(entry)
