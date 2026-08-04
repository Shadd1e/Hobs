# app/orchestrators/booking_orchestrator.py
import logging
from datetime import date, datetime
from typing import Optional

from app.orchestrators.booking_context import BookingContext
from app.conversation.hotel_humanizer import HotelHumanizer
from app.services.booking_service import BookingConflictError

logger = logging.getLogger(__name__)


def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


class BookingOrchestrator:
    """
    Guest-facing booking flow: room Q&A, availability, and the
    create-booking-then-pay sequence. Staff-side inbound (the fuzzy-matched
    "room 4 booked 3 nights" flow) lives in staff_orchestrator.py, not here
    — guests and staff go through different intent classifiers and never
    share a conversation mode.
    """

    def __init__(self, context: BookingContext):
        self.ctx = context
        self.db = context.db
        self.memory = context.memory
        self.merchant_id = str(context.tenant.merchant_id)
        self.client_id = str(context.tenant.client_id)
        self.user_phone = context.user_phone
        self.phone_number_id = context.phone_number_id

    # ==========================================================
    # ROOM INQUIRY
    # ==========================================================

    async def list_room_types(self) -> str:
        room_types = await self.ctx.room_type_service.list_all(
            merchant_id=self.merchant_id, client_id=self.client_id
        )
        payload = [
            {"name": rt.name, "description": rt.description, "price": rt.price}
            for rt in room_types
        ]
        return HotelHumanizer.room_types_list(
            self.ctx.tenant.client_name or "the hotel", payload
        )

    async def answer_open_question(self, question: str) -> str:
        from app.infrastructure.ai.booking_intent_service import answer_room_question
        room_types = await self.ctx.room_type_service.list_all(
            merchant_id=self.merchant_id, client_id=self.client_id
        )
        payload = [
            {"name": rt.name, "description": rt.description, "price": rt.price}
            for rt in room_types
        ]
        return await answer_room_question(
            question, self.ctx.tenant.client_name or "the hotel", payload
        )

    # ==========================================================
    # AVAILABILITY CHECK
    # ==========================================================

    async def check_availability(
        self, room_type_name: Optional[str], check_in_str: Optional[str], check_out_str: Optional[str]
    ) -> str:
        check_in = _parse_date(check_in_str)
        check_out = _parse_date(check_out_str)

        if not check_in or not check_out:
            await self.memory.set_mode("awaiting_dates")
            if room_type_name:
                await self.memory.set_temp_data("pending_room_type_name", room_type_name)
            return HotelHumanizer.ask_for_dates()

        if check_out <= check_in:
            return "Check-out needs to be after check-in — mind sending the dates again?"

        room_type = await self._resolve_room_type(room_type_name)

        available_rooms = await self.ctx.booking_service.find_available_rooms(
            self.merchant_id, self.client_id, check_in, check_out,
            room_type_id=room_type.id if room_type else None,
        )

        if not available_rooms:
            await self.memory.set_mode("idle")
            if room_type_name:
                return HotelHumanizer.availability_result(False, room_type_name, 0, 0)
            return HotelHumanizer.no_rooms_available_at_all()

        chosen_room = available_rooms[0]
        nights = (check_out - check_in).days
        total = await self.ctx.booking_service.calculate_price(chosen_room.id, check_in, check_out)

        # Stash everything needed to actually create the booking once the
        # guest confirms — nothing is written to the DB yet.
        await self.memory.set_temp_data("pending_booking", {
            "room_id": str(chosen_room.id),
            "room_type_name": room_type.name if room_type else None,
            "check_in": check_in.isoformat(),
            "check_out": check_out.isoformat(),
            "nights": nights,
            "total": float(total),
        })
        await self.memory.set_mode("confirming_booking_name")

        rt_name = room_type.name if room_type else "room"
        return HotelHumanizer.availability_result(True, rt_name, nights, float(total)) + \
            "\n\n" + HotelHumanizer.ask_guest_name()

    async def _resolve_room_type(self, name: Optional[str]):
        """
        NOTE: this is a simple case-insensitive substring match, NOT the
        real fuzzy-matching pipeline (pg_trgm + rapidfuzz) that
        app/services/fuzzy_match.py uses for products — that class is
        hard-wired to query Product/Inventory directly and can't be reused
        as-is here. Good enough for "deluxe" matching "Deluxe Room", but
        will NOT catch real typos ("delux", "deluxx"). The staff-side flow
        (Phase 5) genuinely needs typo tolerance per the product spec, so
        that's where a proper RoomTypeFuzzyMatcher (a real port of the
        pg_trgm/rapidfuzz pipeline against RoomType instead of Product)
        should get built — and this method should then call that too,
        rather than staying as this placeholder.
        """
        if not name:
            return None
        room_types = await self.ctx.room_type_service.list_all(
            merchant_id=self.merchant_id, client_id=self.client_id
        )
        if not room_types:
            return None
        name_lower = name.strip().lower()
        for rt in room_types:
            if name_lower == rt.name.strip().lower():
                return rt
        for rt in room_types:
            if name_lower in rt.name.lower() or rt.name.lower() in name_lower:
                return rt
        return None

    # ==========================================================
    # GUEST NAME → BOOKING SUMMARY CONFIRM
    # ==========================================================

    async def provide_guest_name(self, name: str) -> str:
        pending = await self.memory.get_temp_data("pending_booking")
        if not pending:
            await self.memory.set_mode("idle")
            return HotelHumanizer.fallback()

        pending["guest_name"] = name.strip()[:100]
        await self.memory.set_temp_data("pending_booking", pending)
        await self.memory.set_mode("confirming_booking")

        return HotelHumanizer.booking_summary_confirm(
            room_type_name=pending.get("room_type_name") or "room",
            check_in=pending["check_in"],
            check_out=pending["check_out"],
            nights=pending["nights"],
            total=pending["total"],
            guest_name=pending["guest_name"],
        )

    # ==========================================================
    # CONFIRM → CREATE BOOKING + PAYMENT LINK
    # ==========================================================

    async def confirm_booking(self) -> str:
        pending = await self.memory.get_temp_data("pending_booking")
        if not pending:
            await self.memory.set_mode("idle")
            return HotelHumanizer.fallback()

        from app.schemas.room_booking import RoomBookingCreate
        from app.models.room_booking import BookingSource
        import os

        try:
            booking_data = RoomBookingCreate(
                room_id=pending["room_id"],
                merchant_id=self.merchant_id,
                client_id=self.client_id,
                guest_name=pending.get("guest_name"),
                guest_phone=self.user_phone,
                check_in=_parse_date(pending["check_in"]),
                check_out=_parse_date(pending["check_out"]),
                source=BookingSource.GUEST_WHATSAPP,
            )
            booking = await self.ctx.booking_service.create_booking(booking_data)

            redirect_url = os.getenv("FLUTTERWAVE_REDIRECT_URL", "")
            if redirect_url:
                sep = "&" if "?" in redirect_url else "?"
                redirect_url = f"{redirect_url}{sep}ref={booking.booking_code}"
                # Pass the hotel's WhatsApp number so the payment-success
                # page can deep-link the guest back to this conversation
                # (mirrors create_flutterwave_payment_link in checkout_service.py).
                try:
                    from sqlalchemy import select
                    from app.models.client_model import Client
                    wa_result = await self.db.execute(
                        select(Client.whatsapp_number).where(Client.id == self.client_id)
                    )
                    store_whatsapp = wa_result.scalar_one_or_none()
                    if store_whatsapp:
                        redirect_url = f"{redirect_url}&wa={store_whatsapp}"
                except Exception:
                    logger.warning(
                        "Could not resolve hotel WhatsApp number for redirect_url", exc_info=True
                    )

            payment_link = await self.ctx.booking_service.generate_payment_link_for_booking(
                booking, redirect_url
            )
        except BookingConflictError:
            await self.memory.set_mode("idle")
            await self.memory.clear_temp()
            return HotelHumanizer.availability_result(
                False, pending.get("room_type_name"), 0, 0
            )
        except Exception as e:
            logger.exception("Booking creation/payment link failed: %s", e)
            await self.memory.set_mode("idle")
            return "Sorry, something went wrong setting up your booking — could you try again?"

        await self.memory.set_mode("awaiting_booking_payment")
        await self.memory.set_temp_data("awaiting_payment_booking_code", booking.booking_code)

        return HotelHumanizer.payment_link_message(payment_link, pending["total"])

    async def decline_booking(self) -> str:
        await self.memory.set_mode("idle")
        await self.memory.clear_temp()
        return HotelHumanizer._pick([
            "No worries! Let me know if you'd like to check other dates or rooms.",
            "All good — happy to help whenever you're ready.",
        ])

    # ==========================================================
    # BOOKING STATUS
    # ==========================================================

    async def booking_status(self, booking_code: Optional[str]) -> str:
        if not booking_code:
            from sqlalchemy import select, desc
            from app.models.room_booking import RoomBooking
            result = await self.db.execute(
                select(RoomBooking)
                .where(
                    RoomBooking.merchant_id == self.merchant_id,
                    RoomBooking.client_id == self.client_id,
                    RoomBooking.guest_phone == self.user_phone,
                )
                .order_by(desc(RoomBooking.created_at))
                .limit(1)
            )
            booking = result.scalars().first()
            if not booking:
                return "I don't see any bookings under this number yet — want to make one?"
        else:
            from app.models.room_booking import RoomBooking
            booking = await RoomBooking.get_by_booking_code(
                self.db, booking_code.strip().upper(), merchant_id=self.merchant_id
            )
            if not booking:
                return HotelHumanizer.booking_not_found(booking_code)

        room_type = await self._room_type_for_booking(booking)
        return HotelHumanizer.booking_status(
            booking.booking_code,
            booking.status.value,
            room_type.name if room_type else "room",
            booking.check_in.isoformat(),
            booking.check_out.isoformat(),
        )

    async def _room_type_for_booking(self, booking):
        room = await self.ctx.room_service.get(booking.room_id, merchant_id=self.merchant_id)
        if not room:
            return None
        return await self.ctx.room_type_service.get(room.room_type_id, merchant_id=self.merchant_id)
