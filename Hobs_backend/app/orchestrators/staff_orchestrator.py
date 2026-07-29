# app/orchestrators/staff_orchestrator.py
import re
import logging
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.hotel_staff import HotelStaff, ROLE_MANAGER
from app.models.room import Room
from app.services.booking_service import BookingService, BookingConflictError
from app.services.room_service import RoomService
from app.services.room_matcher import RoomMatcher
from app.services.staff_audit_service import StaffAuditService
from app.infrastructure.ai.staff_intent_service import classify_staff_message
from app.conversation.memory import ConversationMemory

logger = logging.getLogger(__name__)

_UNDO_PATTERN = re.compile(r"^\s*undo\s+([A-Za-z0-9]{4,8})\s*$", re.IGNORECASE)
_CONFIRM_WORDS = {"yes", "yeah", "yep", "yup", "ok", "okay", "confirm", "correct", "sure"}
_DECLINE_WORDS = {"no", "nah", "cancel", "wrong", "stop"}


class StaffOrchestrator:
    """
    Entry point for inbound WhatsApp messages from hotel staff.

    Flow, per the product decision to confirm-once before writing anything:
      1. "undo <code>" is checked FIRST, unconditionally -- a manager
         reverting a flagged action isn't subject to the normal confirm
         flow, it's already a deliberate, code-based command.
      2. If the conversation is mid-confirmation (memory mode ==
         "awaiting_staff_confirm"), this message is treated as the yes/no
         reply to the PREVIOUSLY proposed action, not a new message.
      3. Otherwise: extract a new action, permission-check it against the
         staff member's role, propose it back in plain language, and wait
         for confirmation before touching the database at all.

    Every actually-executed action (not just high-impact ones) gets logged
    via StaffAuditService -- see that class for why.
    """

    def __init__(self, db: AsyncSession, merchant_id: str, client_id: str):
        self.db = db
        self.merchant_id = merchant_id
        self.client_id = client_id
        self.booking_service = BookingService(db)
        self.room_service = RoomService(db)
        self.audit_service = StaffAuditService(db)

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
        undo_match = _UNDO_PATTERN.match(message)
        if undo_match:
            return await self._handle_undo(staff, undo_match.group(1).upper())

        memory = await ConversationMemory.load(self.client_id, staff.phone_number)
        mode = await memory.get_mode()

        if mode == "awaiting_staff_confirm":
            return await self._handle_confirmation_reply(staff, memory, message)

        return await self._propose_action(staff, memory, message)

    # ==========================================================
    # STEP 1 -- PROPOSE (extract + permission-check + ask to confirm)
    # ==========================================================
    async def _propose_action(self, staff: HotelStaff, memory: ConversationMemory, message: str) -> str:
        rooms = await self.room_service.list_all(merchant_id=self.merchant_id, client_id=self.client_id)
        real_room_numbers = [r.room_number for r in rooms]

        extracted = await classify_staff_message(message, real_room_numbers)
        action = extracted.get("action", "unclear")

        if action == "status_query":
            return await self._handle_status_query()

        if action == "unclear" or not extracted.get("room_number"):
            return (
                "Sorry, I couldn't tell which room or what happened there -- "
                "try something like 'room 4 booked 3 nights' or 'room 12 checked out'."
            )

        matched_room_number = RoomMatcher.match_room_number(extracted["room_number"], real_room_numbers)
        if not matched_room_number:
            return (
                f"I couldn't match '{extracted['room_number']}' to any room here -- "
                f"our rooms are: {', '.join(real_room_numbers) or '(none set up)'}. Mind resending?"
            )

        room = next((r for r in rooms if r.room_number == matched_room_number), None)
        if not room:
            return "Something went wrong matching that room -- please try again."

        if action == "cancel":
            from app.models.room_booking import RoomBooking, BookingStatus
            active = await RoomBooking.get_active_booking_for_room(self.db, room.id)
            is_paid_cancel = active is not None and active.status in (BookingStatus.PAID, BookingStatus.CHECKED_IN)
            if is_paid_cancel and not staff.can_cancel_paid_booking():
                return (
                    f"\u26a0\ufe0f Room {matched_room_number} has a paid booking -- cancelling it needs a manager. "
                    f"I've noted your request; please ask a manager to do this."
                )

        summary = self._describe_action(action, matched_room_number, extracted)
        await memory.set_temp_data("pending_staff_action", {
            "action": action,
            "room_id": str(room.id),
            "room_number": matched_room_number,
            "guest_name": extracted.get("guest_name"),
            "nights": extracted.get("nights"),
            "raw_message": message,
        })
        await memory.set_mode("awaiting_staff_confirm")
        return f"{summary}\n\nReply *yes* to confirm, or *no* to cancel."

    def _describe_action(self, action: str, room_number: str, extracted: dict) -> str:
        if action == "book":
            nights = extracted.get("nights") or 1
            guest = f" for {extracted['guest_name']}" if extracted.get("guest_name") else ""
            return f"Mark Room {room_number} as *booked*{guest} for {nights} night(s)?"
        if action == "check_in":
            return f"Check *in* Room {room_number}?"
        if action == "check_out":
            return f"Check *out* Room {room_number} (mark it free)?"
        if action == "cancel":
            return f"*Cancel* the booking for Room {room_number}?"
        return f"Apply this update to Room {room_number}?"

    # ==========================================================
    # STEP 2 -- CONFIRM (yes/no reply to the proposed action)
    # ==========================================================
    async def _handle_confirmation_reply(self, staff: HotelStaff, memory: ConversationMemory, message: str) -> str:
        text = message.strip().lower()
        pending = await memory.get_temp_data("pending_staff_action")

        if not pending:
            await memory.set_mode("idle")
            return "Sorry, I lost track of what we were confirming -- could you resend your update?"

        if text in _DECLINE_WORDS:
            await memory.set_mode("idle")
            await memory.clear_temp()
            return "No problem, I didn't make any changes."

        if text not in _CONFIRM_WORDS:
            return "Sorry, just reply *yes* to confirm or *no* to cancel that update."

        await memory.set_mode("idle")
        await memory.clear_temp()

        room = await self.room_service.get(pending["room_id"], merchant_id=self.merchant_id, client_id=self.client_id)
        if not room:
            return "That room seems to have been removed -- please resend your update."

        try:
            return await self._execute_action(staff, room, pending)
        except BookingConflictError as e:
            return f"\u26a0\ufe0f Room {pending['room_number']} already has an overlapping booking -- {e}"
        except ValueError as e:
            return f"\u26a0\ufe0f {e}"
        except Exception as e:
            logger.exception("Staff action execution failed: %s", e)
            return "Something went wrong on my end -- please try again in a moment."

    # ==========================================================
    # STEP 3 -- EXECUTE + LOG
    # ==========================================================
    async def _execute_action(self, staff: HotelStaff, room: Room, pending: dict) -> str:
        action = pending["action"]
        room_number = pending["room_number"]

        if action == "book":
            nights = pending.get("nights") or 1
            booking = await self.booking_service.staff_log_booking(
                merchant_id=self.merchant_id,
                client_id=self.client_id,
                room_id=room.id,
                nights=int(nights),
                staff_phone=staff.phone_number,
                raw_message=pending.get("raw_message", ""),
                guest_name=pending.get("guest_name"),
            )
            await self.audit_service.log_action(
                merchant_id=self.merchant_id, client_id=self.client_id, staff=staff,
                action="book", room_id=room.id, booking_id=booking.id,
                previous_status=None, new_status="PAID",
                raw_message=pending.get("raw_message"), is_high_impact=False,
            )
            guest_part = f" for {booking.guest_name}" if booking.guest_name else ""
            return f"\u2705 Got it -- Room {room_number} booked{guest_part} for {nights} night(s)."

        from app.models.room_booking import RoomBooking, BookingStatus

        active = await RoomBooking.get_active_booking_for_room(self.db, room.id)
        if not active:
            return f"\u26a0\ufe0f No active booking found for Room {room_number}."

        previous_status = active.status.value

        if action == "check_in":
            await self.booking_service.check_in_guest(active.id)
            await self.audit_service.log_action(
                merchant_id=self.merchant_id, client_id=self.client_id, staff=staff,
                action="check_in", room_id=room.id, booking_id=active.id,
                previous_status=previous_status, new_status="CHECKED_IN",
                raw_message=pending.get("raw_message"), is_high_impact=False,
            )
            return f"\u2705 Room {room_number} checked in."

        if action == "check_out":
            await self.booking_service.check_out_guest(active.id)
            await self.audit_service.log_action(
                merchant_id=self.merchant_id, client_id=self.client_id, staff=staff,
                action="check_out", room_id=room.id, booking_id=active.id,
                previous_status=previous_status, new_status="CHECKED_OUT",
                raw_message=pending.get("raw_message"), is_high_impact=False,
            )
            return f"\u2705 Room {room_number} checked out -- now free."

        if action == "cancel":
            is_high_impact = previous_status in (BookingStatus.PAID.value, BookingStatus.CHECKED_IN.value)
            await self.booking_service.cancel_booking(active.id)
            await self.audit_service.log_action(
                merchant_id=self.merchant_id, client_id=self.client_id, staff=staff,
                action="cancel", room_id=room.id, booking_id=active.id,
                previous_status=previous_status, new_status="CANCELLED",
                raw_message=pending.get("raw_message"), is_high_impact=is_high_impact,
            )
            note = " A manager has been notified and can revert this if needed." if is_high_impact else ""
            return f"\u2705 Booking for Room {room_number} cancelled -- room is now free.{note}"

        return "Sorry, I'm not sure what to do with that yet."

    # ==========================================================
    # UNDO -- manager-only, code-based, bypasses the confirm flow entirely
    # ==========================================================
    async def _handle_undo(self, staff: HotelStaff, code: str) -> str:
        if not staff.can_review_flagged_actions():
            return "Sorry, only a manager or above can revert an action."

        try:
            log = await self.audit_service.revert_by_code(self.client_id, code, staff)
        except ValueError as e:
            return f"\u26a0\ufe0f {e}"

        if not log:
            return "I couldn't find an active revert for that code -- it may have expired or already been used."

        return f"\u2705 Reverted. Room status has been restored to {log.new_status or 'its previous state'}."

    # ==========================================================
    # STATUS QUERY (read-only, no confirm needed)
    # ==========================================================
    async def _handle_status_query(self) -> str:
        grid = await self.room_service.dashboard_grid(self.merchant_id, self.client_id)
        if not grid:
            return "No rooms set up yet."
        free = [r["room_number"] for r in grid if not r["is_booked_today"]]
        booked = [r["room_number"] for r in grid if r["is_booked_today"]]
        lines = []
        if free:
            lines.append(f"\U0001F7E2 Free: {', '.join(free)}")
        if booked:
            lines.append(f"\U0001F534 Booked: {', '.join(booked)}")
        return "\n".join(lines) if lines else "No rooms found."
