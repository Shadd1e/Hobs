# app/orchestrators/hotel_conversation_router.py
from typing import Dict, Any
import logging

from app.orchestrators.booking_context import BookingContext
from app.orchestrators.booking_orchestrator import BookingOrchestrator
from app.conversation.hotel_humanizer import HotelHumanizer

logger = logging.getLogger(__name__)


class HotelConversationRouter:
    """
    Guest-facing router, parallel to ConversationRouter (shop domain).
    Same "mode first, then intent" structure as the shop router.
    """

    def __init__(self, context: BookingContext):
        self.ctx = context
        self.booking = BookingOrchestrator(context)
        self.memory = context.memory

    async def route(self, *, intent: str, intent_payload: Dict[str, Any]) -> str:
        current_mode = await self.memory.get_mode()

        # --------------------------------------------------
        # MODE FIRST — stateful booking flow takes priority
        # --------------------------------------------------

        if current_mode == "awaiting_dates":
            check_in = intent_payload.get("check_in")
            check_out = intent_payload.get("check_out")
            if not check_in and not check_out:
                # Guest didn't give parseable dates again — re-prompt rather
                # than silently falling through to unrelated intent handling.
                return HotelHumanizer.ask_for_dates()
            pending_rt = await self.memory.get_temp_data("pending_room_type_name")
            await self.memory.set_mode("idle")
            return await self.booking.check_availability(pending_rt, check_in, check_out)

        if current_mode == "confirming_booking_name":
            if intent in ("cancel",):
                return await self.booking.decline_booking()
            # Treat the raw text as the guest name — this mode expects a
            # name reply, not a re-classified intent.
            return await self.booking.provide_guest_name(self.ctx.user_text)

        if current_mode == "confirming_booking":
            text_lower = self.ctx.user_text.strip().lower()
            _CONFIRM = {"yes", "yeah", "yep", "yup", "ok", "okay", "sure", "confirm", "proceed", "go ahead"}
            _DECLINE = {"no", "nah", "cancel", "never mind", "stop"}
            if intent == "confirm" or text_lower in _CONFIRM:
                return await self.booking.confirm_booking()
            if intent == "cancel" or text_lower in _DECLINE:
                return await self.booking.decline_booking()
            # Ambiguous reply — re-show the pending summary rather than
            # silently falling through to unrelated intent handling.
            pending = await self.memory.get_temp_data("pending_booking")
            if pending:
                return HotelHumanizer.booking_summary_confirm(
                    room_type_name=pending.get("room_type_name") or "room",
                    check_in=pending["check_in"],
                    check_out=pending["check_out"],
                    nights=pending["nights"],
                    total=pending["total"],
                    guest_name=pending.get("guest_name", ""),
                )
            await self.memory.set_mode("idle")

        if current_mode == "awaiting_booking_payment":
            # Guest is texting while a payment link is outstanding — don't
            # start a new booking flow, just remind them.
            if intent in ("book_room", "check_availability", "room_inquiry"):
                return HotelHumanizer._pick([
                    "You've already got a payment link waiting — pay that first and I'll confirm your booking!",
                    "Just waiting on that payment to go through — once it does, you're all set.",
                ])

        # --------------------------------------------------
        # INTENT ROUTING
        # --------------------------------------------------

        if intent == "greeting":
            guest_name = intent_payload.get("guest_name") or await self.memory.get_customer_name()
            return HotelHumanizer.greeting(
                self.ctx.tenant.client_name or "the hotel", guest_name
            )

        if intent == "room_inquiry":
            return await self.booking.list_room_types()

        if intent == "check_availability" or intent == "book_room":
            return await self.booking.check_availability(
                intent_payload.get("room_type_name"),
                intent_payload.get("check_in"),
                intent_payload.get("check_out"),
            )

        if intent == "provide_guest_name":
            return await self.booking.provide_guest_name(
                intent_payload.get("guest_name") or self.ctx.user_text
            )

        if intent == "confirm_booking" or intent == "confirm":
            pending = await self.memory.get_temp_data("pending_booking")
            if pending:
                return await self.booking.confirm_booking()
            return HotelHumanizer._pick(["Sure! What would you like to confirm?"])

        if intent == "cancel_booking":
            return await self.booking.decline_booking()

        if intent == "booking_status":
            return await self.booking.booking_status(intent_payload.get("booking_code"))

        if intent == "help":
            return HotelHumanizer.help()

        if intent == "human_handoff":
            return self._handle_human_handoff()

        if intent == "other":
            # Not a recognised structured intent — try the open-ended,
            # catalogue-grounded LLM answer before giving up to fallback.
            answer = await self.booking.answer_open_question(self.ctx.user_text)
            if answer:
                return answer

        return HotelHumanizer.fallback()

    def _handle_human_handoff(self) -> str:
        tenant = self.ctx.tenant
        hotel_name = tenant.client_name or "the hotel"
        if tenant.operator_notify_phone:
            return HotelHumanizer.human_handoff_with_number(
                hotel_name, tenant.operator_notify_phone.lstrip("+")
            )
        return HotelHumanizer.human_handoff_no_number(hotel_name)
