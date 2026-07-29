# app/services/staff_audit_service.py
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.staff_action_log import StaffActionLog, generate_permission_code
from app.models.hotel_staff import HotelStaff, ROLE_MANAGER

logger = logging.getLogger(__name__)

REVERT_WINDOW_MINUTES = 15


class StaffAuditService:
    """
    Every staff-driven booking mutation goes through log_action() —
    including routine ones, not just high-impact ones. is_high_impact
    controls whether a manager gets pinged, not whether the action is
    recorded; separation of duties (see docstring on StaffActionLog) means
    even routine actions need a durable trail.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def log_action(
        self,
        *,
        merchant_id: str,
        client_id: str,
        staff: HotelStaff,
        action: str,
        room_id=None,
        booking_id: Optional[str] = None,
        previous_status: Optional[str] = None,
        new_status: Optional[str] = None,
        raw_message: Optional[str] = None,
        is_high_impact: bool = False,
    ) -> StaffActionLog:
        revert_code = None
        revert_expires_at = None
        if is_high_impact:
            revert_code = generate_permission_code(6)  # reused generator, same shape
            revert_expires_at = datetime.now(timezone.utc) + timedelta(minutes=REVERT_WINDOW_MINUTES)

        log = StaffActionLog(
            merchant_id=merchant_id,
            client_id=client_id,
            staff_id=staff.id,
            staff_phone_snapshot=staff.phone_number,
            room_id=room_id,
            booking_id=booking_id,
            action=action,
            previous_status=previous_status,
            new_status=new_status,
            raw_message=raw_message,
            is_high_impact=is_high_impact,
            revert_code=revert_code,
            revert_expires_at=revert_expires_at,
        )
        self.db.add(log)
        await self.db.commit()
        await self.db.refresh(log)

        if is_high_impact:
            await self._notify_managers(merchant_id, client_id, log, staff)

        return log

    async def _notify_managers(self, merchant_id: str, client_id: str, log: StaffActionLog, actor: HotelStaff):
        from app.services.whatsapp_sender import send_whatsapp_message
        from app.models.client_whatsapp_credential import ClientWhatsAppCredential
        from app.api.v1.workers.background_tasks import fire_and_forget

        managers_stmt = select(HotelStaff).where(
            HotelStaff.client_id == client_id,
            HotelStaff.is_active.is_(True),
        )
        all_staff = (await self.db.execute(managers_stmt)).scalars().all()
        managers = [s for s in all_staff if s.can_review_flagged_actions() and s.id != actor.id]

        if not managers:
            logger.warning("High-impact action logged for client %s but no manager to notify.", client_id)
            return

        cred_stmt = select(ClientWhatsAppCredential).where(
            ClientWhatsAppCredential.client_id == client_id,
            ClientWhatsAppCredential.active.is_(True),
        )
        cred = (await self.db.execute(cred_stmt)).scalar_one_or_none()
        if not cred:
            return

        message = (
            f"⚠️ *High-impact action flagged*\n"
            f"{actor.name or actor.phone_number} did: {log.action} "
            f"(room action, booking {log.booking_id or 'n/a'})\n"
            f"You have {REVERT_WINDOW_MINUTES} min to undo this.\n"
            f"Reply: undo {log.revert_code}"
        )

        for manager in managers:
            fire_and_forget(
                send_whatsapp_message(
                    to_number=manager.phone_number, message=message, phone_number_id=cred.phone_number_id,
                ),
                name=f"notify_manager_{manager.id}_{log.id}",
            )

    # -----------------------------
    # REVERT — via WhatsApp "undo <code>" or dashboard button
    # -----------------------------
    async def revert_by_code(self, client_id: str, code: str, reviewing_staff: HotelStaff) -> Optional[StaffActionLog]:
        stmt = select(StaffActionLog).where(
            StaffActionLog.client_id == client_id,
            StaffActionLog.revert_code == code,
            StaffActionLog.reverted.is_(False),
        )
        log = (await self.db.execute(stmt)).scalar_one_or_none()
        if not log:
            return None

        now = datetime.now(timezone.utc)
        expires = log.revert_expires_at if log.revert_expires_at.tzinfo else log.revert_expires_at.replace(tzinfo=timezone.utc)
        if now > expires:
            return None  # expired — caller should tell the manager it's too late

        return await self._do_revert(log, reviewing_staff)

    async def revert_by_log_id(self, log_id, reviewing_staff: HotelStaff) -> StaffActionLog:
        stmt = select(StaffActionLog).where(StaffActionLog.id == log_id)
        log = (await self.db.execute(stmt)).scalar_one_or_none()
        if not log:
            raise ValueError("Action log not found")
        if log.reverted:
            raise ValueError("This action was already reverted")
        return await self._do_revert(log, reviewing_staff)

    async def _do_revert(self, log: StaffActionLog, reviewing_staff: HotelStaff) -> StaffActionLog:
        # Separation of duties: whoever performed the action cannot be the
        # one to review/revert their own action.
        if log.staff_id == reviewing_staff.id:
            raise ValueError("You cannot revert your own flagged action — another manager must review it.")
        if not reviewing_staff.can_review_flagged_actions():
            raise ValueError("Only a manager or above can revert actions.")

        from app.services.booking_service import BookingService
        from app.models.room_booking import BookingStatus

        if log.booking_id and log.previous_status:
            booking_service = BookingService(self.db)
            await booking_service.revert_booking_status(
                log.booking_id, BookingStatus(log.previous_status), reviewing_staff.id,
            )

        now = datetime.now(timezone.utc)
        log.reviewed = True
        log.reviewed_by_staff_id = reviewing_staff.id
        log.reviewed_at = now
        log.reverted = True

        # New row for the revert itself — original row is never mutated
        # beyond the review/reverted flags, per the append-only design.
        revert_log = StaffActionLog(
            merchant_id=log.merchant_id,
            client_id=log.client_id,
            staff_id=reviewing_staff.id,
            staff_phone_snapshot=reviewing_staff.phone_number,
            room_id=log.room_id,
            booking_id=log.booking_id,
            action="revert",
            previous_status=log.new_status,
            new_status=log.previous_status,
            raw_message=f"Reverted action {log.id}",
            is_high_impact=False,
        )
        self.db.add(revert_log)
        await self.db.flush()

        log.reverted_by_log_id = revert_log.id
        await self.db.commit()
        await self.db.refresh(log)
        return log

    # -----------------------------
    # WEEKLY DIGEST — the "stay just under the threshold" gap-closer
    # -----------------------------
    async def get_weekly_cancellation_summary(self, client_id: str) -> list:
        from datetime import timedelta as _td
        cutoff = datetime.now(timezone.utc) - _td(days=7)
        stmt = select(StaffActionLog).where(
            StaffActionLog.client_id == client_id,
            StaffActionLog.action.in_(["cancel", "revert"]),
            StaffActionLog.created_at >= cutoff,
        ).order_by(StaffActionLog.created_at.desc())
        result = await self.db.execute(stmt)
        return result.scalars().all()
