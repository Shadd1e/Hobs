# app/services/room_service.py
import logging
logger = logging.getLogger(__name__)

from typing import Optional, List
from datetime import date, datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.models.room import Room
from app.models.room_type import RoomType
from app.models.room_booking import RoomBooking, BookingStatus
from app.schemas.room import RoomCreate


class RoomService:
    """
    CRUD for individually numbered rooms, plus the two queries the whole
    product depends on:
      - dashboard_grid(): the starter-level view (room number + free/booked only)
      - admin_room_detail(): the drill-down (who's in it, how long, logged by whom)
    """

    def __init__(self, db: AsyncSession):
        if not db:
            raise ValueError("AsyncSession must be provided")
        self.db = db

    # -----------------------------
    # CREATE
    # -----------------------------
    async def create(self, data: RoomCreate) -> Optional[Room]:
        if not data.merchant_id or not data.client_id:
            return None

        # Confirm the room_type actually belongs to this hotel — prevents
        # a room being wired to another hotel's room type by mistake.
        rt_stmt = select(RoomType).where(
            RoomType.id == data.room_type_id,
            RoomType.client_id == data.client_id,
        )
        rt = (await self.db.execute(rt_stmt)).scalars().first()
        if not rt:
            raise ValueError("room_type_id does not belong to this hotel")

        room = Room(
            room_number=data.room_number,
            room_type_id=data.room_type_id,
            is_active=data.is_active,
            merchant_id=data.merchant_id,
            client_id=data.client_id,
        )

        try:
            self.db.add(room)
            await self.db.commit()
            await self.db.refresh(room)
            return room
        except IntegrityError:
            await self.db.rollback()
            return None  # most likely uq_room_number_per_hotel violated

    # -----------------------------
    # READ
    # -----------------------------
    async def get(
        self,
        room_id,
        merchant_id: Optional[str] = None,
        client_id: Optional[str] = None,
    ) -> Optional[Room]:
        stmt = select(Room).where(Room.id == room_id)
        if merchant_id:
            stmt = stmt.where(Room.merchant_id == merchant_id)
        if client_id:
            stmt = stmt.where(Room.client_id == client_id)
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def list_all(
        self,
        merchant_id: Optional[str] = None,
        client_id: Optional[str] = None,
    ) -> List[Room]:
        stmt = select(Room).options(selectinload(Room.room_type))
        if merchant_id:
            stmt = stmt.where(Room.merchant_id == merchant_id)
        if client_id:
            stmt = stmt.where(Room.client_id == client_id)
        result = await self.db.execute(stmt)
        return result.scalars().all()

    # -----------------------------
    # UPDATE / DELETE
    # -----------------------------
    async def update(
        self,
        room_id,
        payload: dict,
        merchant_id: Optional[str] = None,
        client_id: Optional[str] = None,
    ) -> Optional[Room]:
        room = await self.get(room_id, merchant_id, client_id)
        if not room:
            return None

        payload.pop("merchant_id", None)
        payload.pop("client_id", None)

        for key, value in payload.items():
            if value is not None:
                setattr(room, key, value)

        await self.db.commit()
        await self.db.refresh(room)
        return room

    async def delete(
        self,
        room_id,
        merchant_id: Optional[str] = None,
        client_id: Optional[str] = None,
    ) -> bool:
        room = await self.get(room_id, merchant_id, client_id)
        if not room:
            return False
        await self.db.delete(room)  # cascades to RoomBooking rows — intentional, see Room.bookings relationship
        await self.db.commit()
        return True

    # -----------------------------
    # DASHBOARD — starter view (free/booked only, no guest detail)
    # -----------------------------
    async def dashboard_grid(self, merchant_id: str, client_id: str) -> List[dict]:
        """
        Every room for this hotel with today's status. This is the
        non-admin dashboard view: room number + booked/free, nothing else.
        """
        today = datetime.now(timezone.utc).date()

        rooms_stmt = (
            select(Room)
            .options(selectinload(Room.room_type))
            .where(Room.merchant_id == merchant_id, Room.client_id == client_id)
            .order_by(Room.room_number)
        )
        rooms = (await self.db.execute(rooms_stmt)).scalars().all()

        # One query for all rooms' active bookings today, rather than N+1.
        active_stmt = select(RoomBooking.room_id).where(
            RoomBooking.merchant_id == merchant_id,
            RoomBooking.client_id == client_id,
            RoomBooking.status.in_([BookingStatus.PAID, BookingStatus.CHECKED_IN]),
            RoomBooking.check_in <= today,
            RoomBooking.check_out > today,
        )
        booked_room_ids = {row[0] for row in (await self.db.execute(active_stmt)).all()}

        return [
            {
                "id": room.id,
                "room_number": room.room_number,
                "room_type_name": room.room_type.name if room.room_type else None,
                "room_type_price": room.room_type.price if room.room_type else None,
                "is_active": room.is_active,
                "is_booked_today": room.id in booked_room_ids,
            }
            for room in rooms
        ]

    # -----------------------------
    # DASHBOARD — admin drill-down
    # -----------------------------
    async def admin_room_detail(
        self, room_id, merchant_id: str, client_id: str
    ) -> Optional[dict]:
        """
        Click-through detail for a booked room: guest, how long, who logged
        it. Gated at the API-route level to admin-role staff only — this
        service method itself doesn't enforce the permission, the route does.
        """
        room = await self.get(room_id, merchant_id, client_id)
        if not room:
            return None

        active_booking = await RoomBooking.get_active_booking_for_room(self.db, room_id)

        return {
            "room_number": room.room_number,
            "is_booked_today": active_booking is not None,
            "booking": {
                "guest_name": active_booking.guest_name,
                "guest_phone": active_booking.guest_phone,
                "check_in": active_booking.check_in,
                "check_out": active_booking.check_out,
                "nights": active_booking.nights,
                "total_amount": active_booking.total_amount,
                "amount_paid": active_booking.amount_paid,
                "source": active_booking.source,
                "logged_by_staff_phone": active_booking.logged_by_staff_phone,
                "booking_code": active_booking.booking_code,
            } if active_booking else None,
        }
