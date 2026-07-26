# app/orchestrators/staff_orchestrator.py
import logging
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.hotel_staff import HotelStaff
from app.models.room import Room
from app.services.booking_service import BookingService, BookingConflictError
from app.services.room_service import RoomService
from app.services.room_matcher import RoomMatcher
from app.infrastructure.ai.staff_intent_service import classify_staff_message

logger = logging.getLogger(__name__)


class StaffOrchestrator:
    """
    Entry point for inbound WhatsApp messages from hotel staff. Kept
    separate from BookingOrchestrator/HotelConversationRouter entirely —
    staff and guests never share a conversation mode, and the webhook
    handler (Phase 6) decides which orchestrator to invoke based on
    whether the sender's number is in HotelStaff before either flow runs.
    """

    def __init__(self, db: AsyncSession, merchant_id: str, client_id: str):
        self.db = db
        self.merchant_id = merchant_id
        self.client_id = client_id
        self.booking_service = BookingService(db)
        self.room_service = RoomService(db)

    # ==========================================================
    # WHITELIST CHECK — called by the webhook handler BEFORE routing
    # to this orchestrator at all, but exposed here too so it's not
    # duplicated if something else needs to check staff status.
    # ==========================================================
    @staticmethod
    async def is_staff_number(db: AsyncSession, client_id: str, phone_number: str) -> Optional[HotelStaff]:
        normalized = phone_number.lstrip("+").strip()
        stmt = select(HotelStaff).where(
            HotelStaff.client_id == client_id,
            HotelStaff.phone_number == normalized,
            HotelStaff.is_active.is_(True),
        )
        result = await db.execute(stmt)
        return result.scalars().first()

    # ==========================================================
    # MAIN ENTRYPOINT
    # ==========================================================
    async def handle_message(self, staff: HotelStaff, message: str) -> str:
        rooms = await self.room_service.list_all(
            merchant_id=self.merchant_id, client_id=self.client_id
        )
        real_room_numbers = [r.room_number for r in rooms]

        extracted = await classify_staff_message(message, real_room_numbers)
        action = extracted.get("action", "unclear")

        if action == "status_query":
            return await self._handle_status_query()

        if action == "unclear" or not extracted.get("room_number"):
            return (
                "Sorry, I couldn't tell which room or what happened there — "
                "try something like 'room 4 booked 3 nights' or 'room 12 checked out'."
            )

        matched_room_number = RoomMatcher.match_room_number(
            extracted["room_number"], real_room_numbers
        )
        if not matched_room_number:
            return (
                f"I couldn't match '{extracted['room_number']}' to any room here — "
                f"our rooms are: {', '.join(real_room_numbers) or '(none set up)'}. Mind resending?"
            )

        room = next((r for r in rooms if r.room_number == matched_room_number), None)
        if not room:
            return "Something went wrong matching that room — please try again."

        try:
            if action == "book":
                return await self._handle_book(staff, room, matched_room_number, extracted, message)
            elif action == "check_in":
                return await self._handle_check_in(room, matched_room_number)
            elif action == "check_out":
                return await self._handle_check_out(room, matched_room_number)
            elif action == "cancel":
                return await self._handle_cancel(room, matched_room_number)
        except BookingConflictError as e:
            return f"⚠️ Room {matched_room_number} already has an active booking that overlaps — {e}"
        except ValueError as e:
            return f"⚠️ {e}"
        except Exception as e:
            logger.exception("Staff action %s failed for room %s: %s", action, matched_room_number, e)
            return "Something went wrong on my end — please try again in a moment."

        return "Sorry, I'm not sure what to do with that yet."

    # ==========================================================
    # ACTIONS
    # ==========================================================

    async def _handle_book(self, staff: HotelStaff, room: Room, room_number: str, extracted: dict, raw_message: str) -> str:
        nights = extracted.get("nights") or 1
        booking = await self.booking_service.staff_log_booking(
            merchant_id=self.merchant_id,
            client_id=self.client_id,
            room_id=room.id,
            nights=int(nights),
            staff_phone=staff.phone_number,
            raw_message=raw_message,
            guest_name=extracted.get("guest_name"),
        )
        guest_part = f" for {booking.guest_name}" if booking.guest_name else ""
        return f"✅ Got it — Room {room_number} booked{guest_part} for {nights} night(s)."

    async def _handle_check_in(self, room: Room, room_number: str) -> str:
        from app.models.room_booking import RoomBooking
        active = await RoomBooking.get_active_booking_for_room(self.db, room.id)
        if not active:
            return f"⚠️ No active booking found for Room {room_number} to check in."
        await self.booking_service.check_in_guest(active.id)
        return f"✅ Room {room_number} checked in."

    async def _handle_check_out(self, room: Room, room_number: str) -> str:
        from app.models.room_booking import RoomBooking
        active = await RoomBooking.get_active_booking_for_room(self.db, room.id)
        if not active:
            return f"⚠️ No active booking found for Room {room_number} to check out."
        await self.booking_service.check_out_guest(active.id)
        return f"✅ Room {room_number} checked out — now free."

    async def _handle_cancel(self, room: Room, room_number: str) -> str:
        from app.models.room_booking import RoomBooking
        active = await RoomBooking.get_active_booking_for_room(self.db, room.id)
        if not active:
            return f"⚠️ No active booking found for Room {room_number} to cancel."
        await self.booking_service.cancel_booking(active.id)
        return f"✅ Booking for Room {room_number} cancelled — room is now free."

    async def _handle_status_query(self) -> str:
        grid = await self.room_service.dashboard_grid(self.merchant_id, self.client_id)
        if not grid:
            return "No rooms set up yet."
        free = [r["room_number"] for r in grid if not r["is_booked_today"]]
        booked = [r["room_number"] for r in grid if r["is_booked_today"]]
        lines = []
        if free:
            lines.append(f"🟢 Free: {', '.join(free)}")
        if booked:
            lines.append(f"🔴 Booked: {', '.join(booked)}")
        return "\n".join(lines) if lines else "No rooms found."
