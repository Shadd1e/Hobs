# app/api/v1/hotel_staff_auth.py
#
# Dashboard login for individual HotelStaff (manager/top_manager), separate
# from the merchant/owner login used elsewhere in the dashboard. This was
# flagged as NOT built back in Phase 8 -- closing that gap now because the
# permission-review and role-change flows genuinely need to know WHICH
# staff member is acting, not just which hotel account owns the session.
#
# NOT built here: password self-service reset for staff, invite-by-email
# onboarding flow for new staff accounts. A top_manager currently has to
# set a staff member's password_hash directly (e.g. via a one-off admin
# action) -- flagging honestly rather than pretending this is finished.

import logging
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.hotel_staff import HotelStaff
from app.core.security import verify_password, create_staff_access_token
from app.db.deps import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/hotel/staff", tags=["Hotel Staff Auth"])


class StaffLoginRequest(BaseModel):
    phone_number: str
    password: str


class StaffLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    staff_id: str
    role: str
    name: str | None = None


@router.post("/login", response_model=StaffLoginResponse)
async def staff_login(payload: StaffLoginRequest, db: AsyncSession = Depends(get_db)):
    normalized = payload.phone_number.lstrip("+").strip()
    stmt = select(HotelStaff).where(
        HotelStaff.phone_number == normalized, HotelStaff.is_active.is_(True),
    )
    staff = (await db.execute(stmt)).scalar_one_or_none()

    if not staff or not staff.password_hash or not verify_password(payload.password, staff.password_hash):
        # Deliberately identical error for "no such staff" and "wrong password"
        # -- don't leak which phone numbers are registered.
        raise HTTPException(status_code=401, detail="Invalid phone number or password")

    token = create_staff_access_token(str(staff.id), staff.client_id, staff.merchant_id)
    return StaffLoginResponse(
        access_token=token, staff_id=str(staff.id), role=staff.role, name=staff.name,
    )
