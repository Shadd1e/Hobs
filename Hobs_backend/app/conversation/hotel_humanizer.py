# app/conversation/hotel_humanizer.py
from typing import Optional, List
from app.conversation.humanizer import Humanizer


class HotelHumanizer(Humanizer):
    """
    Guest-facing strings for the booking flow. Subclasses Humanizer purely
    to reuse _pick / _format_currency / _time_greeting — none of the
    shop-specific (cart/product) methods apply here, so this class defines
    its own full set rather than overriding shop methods.

    Same rules as Humanizer: WhatsApp bold = *text*, 3+ phrasing variants
    per method, no robotic confirmations.
    """

    # ── Greeting ──────────────────────────────────────────────────────────────

    @classmethod
    def greeting(cls, hotel_name: str, guest_name: Optional[str] = None) -> str:
        tg = cls._time_greeting()
        if guest_name:
            return cls._pick([
                f"{tg}, {guest_name}! 👋 Welcome back to {hotel_name}. Looking to book a room?",
                f"Hey {guest_name}! Good to hear from you again — what can I help with at {hotel_name}?",
                f"{tg} {guest_name}! 😊 Need a room, or just checking something?",
            ])
        return cls._pick([
            f"{tg}! 👋 Welcome to {hotel_name}. Looking for a room, or have a question first?",
            f"Hi there! Thanks for reaching out to {hotel_name} — how can I help?",
            f"Hello! I'm here for anything room-related at {hotel_name}. What do you need?",
        ])

    # ── Room type listing / Q&A ──────────────────────────────────────────────

    @classmethod
    def room_types_list(cls, hotel_name: str, room_types: List[dict]) -> str:
        """room_types: [{name, description, price}]"""
        if not room_types:
            return cls._pick([
                f"Hmm, looks like {hotel_name} doesn't have any room types set up yet — let me flag that.",
                "I'm not seeing any rooms listed right now, one sec while I sort that out.",
            ])
        lines = [cls._pick([
            f"Here's what we've got at {hotel_name}:",
            f"Sure! Our rooms at {hotel_name}:",
            "Here's the lineup:",
        ]), ""]
        for rt in room_types:
            price = cls._format_currency(rt.get("price", 0))
            desc = rt.get("description")
            line = f"🛏️ *{rt['name']}* — {price}/night"
            if desc:
                line += f"\n   {desc}"
            lines.append(line)
        lines.append("")
        lines.append(cls._pick([
            "Want me to check availability for specific dates?",
            "Tell me your dates and I'll check what's free!",
            "Just say the word if you'd like to book one of these.",
        ]))
        return "\n".join(lines)

    @classmethod
    def ask_for_dates(cls) -> str:
        return cls._pick([
            "Sure! What dates are you looking at? (e.g. check-in and check-out)",
            "Happy to check — when would you be checking in and out?",
            "What dates work for you? Just give me check-in and check-out.",
        ])

    @classmethod
    def ask_for_room_type_or_dates(cls) -> str:
        return cls._pick([
            "Which room type were you thinking, and what dates?",
            "Got a room type in mind? And what dates should I check?",
        ])

    # ── Availability results ──────────────────────────────────────────────────

    @classmethod
    def availability_result(
        cls, available: bool, room_type_name: Optional[str], nights: int, total: float
    ) -> str:
        total_str = cls._format_currency(total)
        if available:
            return cls._pick([
                f"Good news — we've got a {room_type_name or 'room'} free for those {nights} night(s)! "
                f"Total comes to *{total_str}*. Want me to book it?",
                f"You're in luck, that's available! {nights} night(s) at *{total_str}* total. Shall I go ahead and book it?",
                f"Yep, we can do that — {nights} night(s), *{total_str}* total. Ready to book?",
            ])
        return cls._pick([
            f"Ah, sorry — no {room_type_name or 'rooms'} free for those dates. Want me to check a different date range?",
            "Unfortunately that's booked out for those dates. Want to try different dates?",
            "That one's taken for those nights, sorry! Should I check other dates or room types?",
        ])

    @classmethod
    def no_rooms_available_at_all(cls) -> str:
        return cls._pick([
            "Hmm, I'm not finding anything free for those dates across any room type. Want to try different dates?",
            "Looks like we're fully booked for those dates. Different dates in mind?",
        ])

    # ── Booking flow ──────────────────────────────────────────────────────────

    @classmethod
    def ask_guest_name(cls) -> str:
        return cls._pick([
            "Great! What name should I put the booking under?",
            "Perfect, who's this booking for?",
            "Nice — what name for the reservation?",
        ])

    @classmethod
    def booking_summary_confirm(
        cls, room_type_name: str, check_in: str, check_out: str, nights: int, total: float, guest_name: str
    ) -> str:
        total_str = cls._format_currency(total)
        return cls._pick([
            f"Let's confirm: *{room_type_name}*, {check_in} → {check_out} ({nights} night(s)), "
            f"under *{guest_name}*, total *{total_str}*. Shall I send the payment link?",
            f"Just to double-check — *{room_type_name}* from {check_in} to {check_out}, "
            f"{nights} night(s), guest name *{guest_name}*, *{total_str}* total. Good to proceed?",
        ])

    @classmethod
    def payment_link_message(cls, link: str, total: float) -> str:
        total_str = cls._format_currency(total)
        return cls._pick([
            f"Here's your payment link — *{total_str}*:\n{link}\n\nOnce it's paid I'll confirm your booking right away!",
            f"All set! Pay *{total_str}* here:\n{link}\n\nI'll send confirmation as soon as it goes through.",
        ])

    @classmethod
    def booking_confirmed_guest(
        cls, hotel_name: str, room_type_name: str, check_in: str, check_out: str, booking_code: str
    ) -> str:
        return cls._pick([
            f"✅ You're all booked in at {hotel_name}! *{room_type_name}*, {check_in} → {check_out}. "
            f"Your booking code is *{booking_code}* — see you soon!",
            f"🎉 Payment received — you're confirmed! *{room_type_name}* from {check_in} to {check_out} "
            f"at {hotel_name}. Booking code: *{booking_code}*.",
        ])

    @classmethod
    def checkout_reminder(cls, hotel_name: str, check_out: str, guest_name: Optional[str] = None) -> str:
        name_part = f"{guest_name}, " if guest_name else ""
        return cls._pick([
            f"Hi {name_part}just a heads up — your check-out at {hotel_name} is on {check_out}. "
            f"Let us know if you'd like to extend your stay!",
            f"Reminder: {name_part}check-out at {hotel_name} is {check_out}. Hope you enjoyed your stay so far!",
        ])

    @classmethod
    def booking_cancelled(cls) -> str:
        return cls._pick([
            "No problem, I've cancelled that booking.",
            "Done — that booking's been cancelled.",
        ])

    @classmethod
    def booking_status(cls, booking_code: str, status: str, room_type_name: str, check_in: str, check_out: str) -> str:
        status_label = {
            "CREATED": "Just started, not paid yet",
            "PENDING_PAYMENT": "Waiting on payment",
            "PAID": "Confirmed ✅",
            "CHECKED_IN": "Checked in 🛎️",
            "CHECKED_OUT": "Checked out",
            "CANCELLED": "Cancelled",
            "REFUNDED": "Refunded",
        }.get(status, status)
        return (
            f"*Booking {booking_code}*\n"
            f"Status: {status_label}\n"
            f"Room: {room_type_name}\n"
            f"Dates: {check_in} → {check_out}"
        )

    @classmethod
    def booking_not_found(cls, code: str) -> str:
        return cls._pick([
            f"Hmm, I can't find a booking with code {code}. Mind double-checking it?",
            f"No booking found for {code} — could you confirm the code?",
        ])

    # ── Fallback / help ─────────────────────────────────────────────────────

    @classmethod
    def fallback(cls) -> str:
        return cls._pick([
            "Sorry, I didn't quite catch that — you can ask about our rooms, check availability, or book a stay!",
            "Not sure I understood — try asking about room types, dates, or say *book* to get started.",
            "Hmm, could you rephrase that? I can help with room info, availability, and bookings.",
        ])

    @classmethod
    def help(cls) -> str:
        return cls._pick([
            "I can tell you about our rooms, check what's free for your dates, and get you booked in! "
            "Just tell me what you're looking for.",
        ])

    @classmethod
    def human_handoff_with_number(cls, hotel_name: str, number: str) -> str:
        return cls._pick([
            f"I'll get someone from {hotel_name} to reach out — you can also message the front desk directly at wa.me/{number}.",
        ])

    @classmethod
    def human_handoff_no_number(cls, hotel_name: str) -> str:
        return cls._pick([
            f"Let me flag this for the {hotel_name} team — someone will follow up with you shortly.",
        ])
