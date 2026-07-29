# app/services/permission_change_service.py
#
# The ONLY path by which a HotelStaff.role can change. See
# PermissionChangeRequest's docstring -- this is deliberately unreachable
# from WhatsApp, dashboard-only, gated by a code emailed to the requesting
# top_manager's own registered address.

import logging
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.hotel_staff import HotelStaff, ROLE_TOP_MANAGER, ROLE_RECEPTIONIST, ROLE_MANAGER
from app.models.permission_change_request import PermissionChangeRequest

logger = logging.getLogger(__name__)

_VALID_ROLES = {ROLE_RECEPTIONIST, ROLE_MANAGER, ROLE_TOP_MANAGER}
MAX_CONFIRM_ATTEMPTS = 5


class PermissionChangeService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def initiate(
        self, *, merchant_id: str, client_id: str, requesting_staff: HotelStaff,
        target_staff_id, new_role: str,
    ) -> PermissionChangeRequest:
        if not requesting_staff.can_assign_roles():
            raise ValueError("Only a top manager can change staff roles.")
        if new_role not in _VALID_ROLES:
            raise ValueError(f"Invalid role: {new_role}")
        if not requesting_staff.email:
            raise ValueError("You need a registered email on file before changing permissions.")

        target_stmt = select(HotelStaff).where(
            HotelStaff.id == target_staff_id, HotelStaff.client_id == client_id,
        )
        target = (await self.db.execute(target_stmt)).scalar_one_or_none()
        if not target:
            raise ValueError("Staff member not found.")

        request = PermissionChangeRequest(
            merchant_id=merchant_id,
            client_id=client_id,
            requested_by_staff_id=requesting_staff.id,
            target_staff_id=target.id,
            old_role=target.role,
            new_role=new_role,
            email_sent_to=requesting_staff.email,
        )
        self.db.add(request)
        await self.db.commit()
        await self.db.refresh(request)

        await self._send_code_email(requesting_staff.email, target.name or target.phone_number, new_role, request.code)
        return request

    async def _send_code_email(self, to_email: str, target_name: str, new_role: str, code: str):
        from app.services.email_service import send_email

        subject = "Confirm staff permission change"
        html = f"""
        <div style="font-family:Arial,sans-serif;padding:20px">
          <p>You requested to change <strong>{target_name}</strong>'s role to
          <strong>{new_role}</strong>.</p>
          <p style="font-size:28px;font-weight:700;letter-spacing:4px">{code}</p>
          <p>This code expires in 10 minutes. If you didn't request this, ignore this email --
          the change will not apply without this code.</p>
        </div>
        """
        text = (
            f"You requested to change {target_name}'s role to {new_role}.\n"
            f"Confirmation code: {code}\n"
            f"Expires in 10 minutes. If you didn't request this, ignore this email."
        )
        try:
            await send_email(to_email, subject, html, text)
        except Exception as e:
            logger.error("Failed to send permission-change code email: %s", e)

    async def confirm(
        self, *, request_id, code: str, confirming_staff: HotelStaff,
    ) -> HotelStaff:
        stmt = select(PermissionChangeRequest).where(PermissionChangeRequest.id == request_id)
        request = (await self.db.execute(stmt)).scalar_one_or_none()
        if not request:
            raise ValueError("Request not found.")

        if request.requested_by_staff_id != confirming_staff.id:
            raise ValueError("Only the staff member who requested this change can confirm it.")

        if not request.is_pending:
            raise ValueError("This request has expired or was already used.")

        if request.attempts >= MAX_CONFIRM_ATTEMPTS:
            raise ValueError("Too many incorrect attempts -- please start a new request.")

        if request.code != code.strip():
            request.attempts += 1
            await self.db.commit()
            raise ValueError("Incorrect code.")

        target_stmt = select(HotelStaff).where(HotelStaff.id == request.target_staff_id)
        target = (await self.db.execute(target_stmt)).scalar_one_or_none()
        if not target:
            raise ValueError("Target staff member no longer exists.")

        target.role = request.new_role
        request.confirmed_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(target)

        logger.info(
            "Permission change confirmed: staff %s role %s -> %s (by %s)",
            target.id, request.old_role, request.new_role, confirming_staff.id,
        )
        return target
