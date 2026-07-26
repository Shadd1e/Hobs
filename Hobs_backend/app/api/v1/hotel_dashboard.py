# app/api/v1/hotel_dashboard.py
#
# Dashboard API for hotel owners/admins. Reuses the EXISTING merchant JWT
# auth (request.state.merchant_id, set by TenantMiddleware) rather than
# building a second auth system -- this is the same mechanism ShoprHQ's
# admin dashboard endpoints already use (see app/api/v1/product.py's
# /admin/ routes), and a hotel group owner logging into the dashboard is
# functionally the same actor as a store owner: an authenticated Merchant.
#
# NOT built here: individual HotelStaff dashboard logins with role-based
# restriction (front_desk vs admin/manager, per HotelStaff.role and its
# nullable password_hash). That's a separate, smaller piece of work --
# flagging it explicitly rather than half-building a second auth path
# under time pressure. Every endpoint below assumes "the hotel owner/
# manager is logged in", which is what "admin-level detail" meant in the
# original spec (room grid = starter view, click-through = admin view --
# both currently gated the same way, at the merchant-JWT level, not yet
# split further by individual staff role).

import logging
logger = logging.getLogger(__name__)

from fastapi import APIRouter, HTTPException, Depends, Query, Request
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.client_model import Client
from app.models.room_booking import RoomBooking

from app.schemas.room_type import RoomTypeCreate, RoomTypeUpdate, RoomTypeRead
from app.schemas.room import RoomCreate, RoomUpdate, RoomRead, RoomStatusRead
from app.schemas.room_booking import RoomBookingAdminRead

from app.services.room_type_service import RoomTypeService
from app.services.room_service import RoomService

from app.db.deps import get_db

router = APIRouter(prefix="/hotel", tags=["Hotel Dashboard"])


# ==========================================================
# SHARED AUTH/OWNERSHIP HELPER
# ==========================================================
async def _authenticated_merchant_id(request: Request) -> str:
    merchant_id = getattr(request.state, "merchant_id", None)
    if not merchant_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    return merchant_id


async def _verify_hotel_ownership(db: AsyncSession, client_id: str, merchant_id: str) -> None:
    """
    Confirms client_id (the hotel) actually belongs to the authenticated
    merchant -- without this, any logged-in merchant could pass another
    hotel's client_id and see/edit its data. Same guard pattern as
    product.py's admin routes.
    """
    result = await db.execute(
        select(Client.id).where(Client.id == client_id, Client.merchant_id == merchant_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Hotel does not belong to this account")


# ==========================================================
# DASHBOARD GRID -- starter view (room number + free/booked only)
# ==========================================================
@router.get("/dashboard/rooms")
async def dashboard_rooms(
    client_id: str = Query(..., description="Hotel ID"),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
):
    merchant_id = await _authenticated_merchant_id(request)
    await _verify_hotel_ownership(db, client_id, merchant_id)

    room_service = RoomService(db)
    return await room_service.dashboard_grid(merchant_id, client_id)


# ==========================================================
# ADMIN DRILL-DOWN -- who's in the room, how long, logged by whom
# ==========================================================
@router.get("/dashboard/rooms/{room_id}")
async def dashboard_room_detail(
    room_id: str,
    client_id: str = Query(...),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
):
    merchant_id = await _authenticated_merchant_id(request)
    await _verify_hotel_ownership(db, client_id, merchant_id)

    room_service = RoomService(db)
    detail = await room_service.admin_room_detail(room_id, merchant_id, client_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Room not found")
    return detail


# ==========================================================
# ROOM TYPES -- CRUD, price adjustment lives in the PATCH endpoint
# ==========================================================
@router.post("/room-types", response_model=RoomTypeRead)
async def create_room_type(
    payload: RoomTypeCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    merchant_id = await _authenticated_merchant_id(request)
    await _verify_hotel_ownership(db, payload.client_id, merchant_id)

    if payload.merchant_id != merchant_id:
        raise HTTPException(status_code=403, detail="merchant_id does not match authenticated account")

    room_type = await RoomTypeService(db).create(payload)
    if not room_type:
        raise HTTPException(status_code=409, detail="A room type with this name already exists for this hotel")
    return room_type


@router.get("/room-types", response_model=List[RoomTypeRead])
async def list_room_types(
    client_id: str = Query(...),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
):
    merchant_id = await _authenticated_merchant_id(request)
    await _verify_hotel_ownership(db, client_id, merchant_id)
    return await RoomTypeService(db).list_all(merchant_id=merchant_id, client_id=client_id)


@router.patch("/room-types/{room_type_id}", response_model=RoomTypeRead)
async def update_room_type(
    room_type_id: str,
    payload: RoomTypeUpdate,
    client_id: str = Query(...),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
):
    """The price-adjustment endpoint -- same shape as store owners adjusting product prices."""
    merchant_id = await _authenticated_merchant_id(request)
    await _verify_hotel_ownership(db, client_id, merchant_id)

    updated = await RoomTypeService(db).update(
        room_type_id, payload.model_dump(exclude_unset=True), merchant_id=merchant_id, client_id=client_id,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Room type not found")
    return updated


@router.delete("/room-types/{room_type_id}")
async def delete_room_type(
    room_type_id: str,
    client_id: str = Query(...),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
):
    merchant_id = await _authenticated_merchant_id(request)
    await _verify_hotel_ownership(db, client_id, merchant_id)

    try:
        deleted = await RoomTypeService(db).delete(room_type_id, merchant_id=merchant_id, client_id=client_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    if not deleted:
        raise HTTPException(status_code=404, detail="Room type not found")
    return {"status": "deleted"}


# ==========================================================
# ROOMS -- CRUD for individual numbered rooms
# ==========================================================
@router.post("/rooms", response_model=RoomRead)
async def create_room(
    payload: RoomCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    merchant_id = await _authenticated_merchant_id(request)
    await _verify_hotel_ownership(db, payload.client_id, merchant_id)

    if payload.merchant_id != merchant_id:
        raise HTTPException(status_code=403, detail="merchant_id does not match authenticated account")

    try:
        room = await RoomService(db).create(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not room:
        raise HTTPException(status_code=409, detail="A room with this number already exists for this hotel")
    return room


@router.get("/rooms", response_model=List[RoomRead])
async def list_rooms(
    client_id: str = Query(...),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
):
    merchant_id = await _authenticated_merchant_id(request)
    await _verify_hotel_ownership(db, client_id, merchant_id)
    return await RoomService(db).list_all(merchant_id=merchant_id, client_id=client_id)


@router.patch("/rooms/{room_id}", response_model=RoomRead)
async def update_room(
    room_id: str,
    payload: RoomUpdate,
    client_id: str = Query(...),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
):
    merchant_id = await _authenticated_merchant_id(request)
    await _verify_hotel_ownership(db, client_id, merchant_id)

    updated = await RoomService(db).update(
        room_id, payload.model_dump(exclude_unset=True), merchant_id=merchant_id, client_id=client_id,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Room not found")
    return updated


@router.delete("/rooms/{room_id}")
async def delete_room(
    room_id: str,
    client_id: str = Query(...),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
):
    merchant_id = await _authenticated_merchant_id(request)
    await _verify_hotel_ownership(db, client_id, merchant_id)

    deleted = await RoomService(db).delete(room_id, merchant_id=merchant_id, client_id=client_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Room not found")
    return {"status": "deleted"}


# ==========================================================
# BOOKING LOOKUP -- admin-level detail by booking code
# ==========================================================
@router.get("/bookings/{booking_code}", response_model=RoomBookingAdminRead)
async def get_booking(
    booking_code: str,
    client_id: str = Query(...),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
):
    merchant_id = await _authenticated_merchant_id(request)
    await _verify_hotel_ownership(db, client_id, merchant_id)

    booking = await RoomBooking.get_by_booking_code(db, booking_code.strip().upper(), merchant_id=merchant_id, client_id=client_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    return booking


@router.get("/bookings", response_model=List[RoomBookingAdminRead])
async def list_bookings(
    client_id: str = Query(...),
    status: Optional[str] = Query(None, description="Filter by booking status"),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
):
    merchant_id = await _authenticated_merchant_id(request)
    await _verify_hotel_ownership(db, client_id, merchant_id)

    stmt = select(RoomBooking).where(
        RoomBooking.merchant_id == merchant_id, RoomBooking.client_id == client_id,
    ).order_by(RoomBooking.created_at.desc())
    if status:
        stmt = stmt.where(RoomBooking.status == status.upper())

    result = await db.execute(stmt)
    return result.scalars().all()
