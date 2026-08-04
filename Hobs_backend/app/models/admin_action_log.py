# app/models/admin_action_log.py
"""
AdminActionLog — append-only audit trail for every admin-dashboard action
that mutates something (approve/reject an application, suspend/unsuspend
a merchant's messaging, approve/reject a submitted verification, etc).

Same "tamper-evident" idea as StaffActionLog (app/models/staff_action_log.py),
but taken one step further: it isn't just application-code convention that
nothing UPDATEs or DELETEs a row here. Migration 0023 attaches a Postgres
trigger that raises an exception on UPDATE or DELETE against this table —
enforced by the database itself, not by which endpoints happen to exist.
"No matter the level" means this holds regardless of admin role or which
code path is calling it; the only way to remove a row is a manual, logged
DBA operation outside the application entirely.

Admin identity today: there is currently ONE shared admin credential
(ADMIN_SECRET), not individual named admin accounts — see _require_admin()
in api/v1/admin_whatsapp.py. actor_session_id is the best attribution
available right now (a truncated, non-reversible hash of the admin session
token, so at least distinct login sessions are distinguishable). If/when
named admin accounts exist, swap this for a real actor_id/actor_name and
backfill won't be needed since old rows just keep their session hash.
"""
from sqlalchemy import Column, String, Text, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
import uuid

from app.db.base import Base


class AdminActionLog(Base):
    __tablename__ = "admin_action_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    actor_session_id = Column(
        String(16), nullable=False,
        comment="Truncated sha256 of the X-Admin-Token used. Best-available actor "
                "attribution until named admin accounts exist.",
    )
    ip_address = Column(String(64), nullable=True)

    action = Column(
        String(60), nullable=False, index=True,
        comment="e.g. application.approved, application.rejected, "
                "merchant.messaging_suspended, verification.approved",
    )
    target_type = Column(String(40), nullable=False, comment="e.g. merchant_application, merchant")
    target_id   = Column(String(40), nullable=False, index=True)

    detail = Column(Text, nullable=True, comment="Free-text / JSON context — reason, previous state, etc.")

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    def __repr__(self):
        return f"<AdminActionLog(action={self.action!r}, target={self.target_type}:{self.target_id})>"
