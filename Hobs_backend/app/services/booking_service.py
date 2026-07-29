# app/services/booking_service.py
import logging
logger = logging.getLogger(__name__)

import os
import httpx
from typing import Optional
from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.room import Room
from app.models.room_type import RoomType
from app.models.room_booking import RoomBooking, BookingStatus, BookingSource
from app.schemas.room_booking import RoomBookingCreate
from app.services.flutterwave_subaccount_service import FlutterwaveSubaccountService

FLUTTERWAVE_BASE = "https://api.flutterwave.com/v3"


class BookingConflictError(Exception):
    """Raised when the requested room is not available for the requested dates."""
    pass


class BookingService:
    """
    Core booking logic. Both the guest WhatsApp flow and the staff WhatsApp
    flow call into this — neither talks to the RoomBooking model directly.

    Locking note: per the product decision, availability is only enforced
    at PAID, not at booking-creation time. So create_booking() does NOT
    reserve/lock the room — it only checks that no PAID/CHECKED_IN booking
    already overlaps. Two guests can still both reach PENDING_PAYMENT for
    the same room; the second one to actually pay will hit a conflict at
    confirm_payment() and needs to be refunded. This is the known tradeoff
    flagged earlier — a short soft-hold on PENDING_PAYMENT is the natural
    place to close that gap later without changing this service's shape.
    """

    def __init__(self, db: AsyncSession):
        if not db:
            raise ValueError("AsyncSession must be provided")
        self.db = db

    # -----------------------------
    # PAYMENT LINK GENERATION (Flutterwave — see docs/WIRING_NOTES.md)
    # -----------------------------
    async def generate_payment_link_for_booking(self, booking: RoomBooking, redirect_url: str) -> str:
        """
        Moves the booking to PENDING_PAYMENT and returns a Flutterwave
        checkout link. Called by the guest WhatsApp flow right after
        create_booking(). Splits to the hotel's Flutterwave subaccount if
        one is registered; otherwise the full amount settles to the
        platform account (same fallback behaviour as ShoprHQ's Paystack
        flow, just flagged via logger.warning instead of failing outright).
        """
        subaccount_service = FlutterwaveSubaccountService(self.db)
        subaccount_id = await subaccount_service.get_subaccount_id(
            booking.client_id, booking.merchant_id
        )
        if not subaccount_id:
            logger.warning(
                "No Flutterwave subaccount for hotel %s — payment will settle "
                "to the platform account, not the hotel.",
                booking.client_id,
            )

        payment_link = await self.create_flutterwave_payment_link(
            reference=booking.booking_code,
            amount_naira=float(booking.total_amount),
            phone=booking.guest_phone or "",
            guest_name=booking.guest_name,
            subaccount_id=subaccount_id,
            redirect_url=redirect_url,
        )

        await booking.transition_to(BookingStatus.PENDING_PAYMENT, self.db)
        await self.db.commit()
        await self.db.refresh(booking)
        return payment_link

    async def create_flutterwave_payment_link(
        self,
        *,
        reference: str,
        amount_naira: float,
        phone: str,
        guest_name: Optional[str] = None,
        subaccount_id: Optional[str] = None,
        redirect_url: str = "",
    ) -> str:
        # Reads PAYSTACK_SECRET_KEY on purpose — holds the Flutterwave
        # secret key in this deployment. See docs/WIRING_NOTES.md.
        secret = os.getenv("PAYSTACK_SECRET_KEY")
        if not secret:
            raise ValueError(
                "PAYSTACK_SECRET_KEY not configured (holds the Flutterwave "
                "secret key — see docs/WIRING_NOTES.md)"
            )

        email = f"{(phone or reference).replace('+', '')}@hobs.app"

        payload = {
            "tx_ref": reference,               # == booking.booking_code, used to look up the booking in the webhook
            "amount": amount_naira,
            "currency": "NGN",
            "redirect_url": redirect_url,
            "customer": {
                "email": email,
                "phonenumber": phone or None,
                "name": guest_name or "Guest",
            },
            "customizations": {
                "title": "Room booking payment",
            },
        }

        if subaccount_id:
            # Flutterwave applies the split_value set at subaccount-creation
            # time — no per-transaction percentage needed here.
            payload["subaccounts"] = [{"id": subaccount_id}]

        headers = {
            "Authorization": f"Bearer {secret}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                f"{FLUTTERWAVE_BASE}/payments",
                json=payload,
                headers=headers,
            )

        if response.status_code not in (200, 201):
            logger.error("Flutterwave init error %s: %s", response.status_code, response.text)
            raise ValueError("Failed to initialize Flutterwave payment")

        data = response.json()
        link = data.get("data", {}).get("link")
        if not link:
            raise ValueError("Flutterwave did not return a payment link")
        return link

    # -----------------------------
    # AVAILABILITY + PRICING
    # -----------------------------
    async def check_availability(self, room_id, check_in: date, check_out: date) -> bool:
        return await RoomBooking.is_room_available(self.db, room_id, check_in, check_out)

    async def calculate_price(self, room_id, check_in: date, check_out: date) -> Decimal:
        room_stmt = select(Room).where(Room.id == room_id)
        room = (await self.db.execute(room_stmt)).scalars().first()
        if not room:
            raise ValueError("Room not found")

        rt_stmt = select(RoomType).where(RoomType.id == room.room_type_id)
        room_type = (await self.db.execute(rt_stmt)).scalars().first()
        if not room_type:
            raise ValueError("Room type not found")

        nights = (check_out - check_in).days
        if nights <= 0:
            raise ValueError("check_out must be after check_in")

        return Decimal(str(room_type.price)) * nights

    async def find_available_rooms(
        self,
        merchant_id: str,
        client_id: str,
        check_in: date,
        check_out: date,
        room_type_id=None,
    ) -> list:
        """Used by the guest bot when it asks 'what's free for these dates'."""
        stmt = select(Room).where(
            Room.merchant_id == merchant_id,
            Room.client_id == client_id,
            Room.is_active == True,
        )
        if room_type_id:
            stmt = stmt.where(Room.room_type_id == room_type_id)

        candidate_rooms = (await self.db.execute(stmt)).scalars().all()

        available = []
        for room in candidate_rooms:
            if await self.check_availability(room.id, check_in, check_out):
                available.append(room)
        return available

    # -----------------------------
    # CREATE BOOKING
    # -----------------------------
    async def create_booking(self, data: RoomBookingCreate) -> RoomBooking:
        """
        Creates a booking in CREATED status. Caller (guest flow) then moves
        it to PENDING_PAYMENT once a Flutterwave payment link is generated,
        or (staff flow) may jump straight to PAID if staff say payment's
        already been collected — see staff_log_booking() below.
        """
        if not await self.check_availability(data.room_id, data.check_in, data.check_out):
            raise BookingConflictError(
                f"Room is already booked for an overlapping date range."
            )

        total_amount = await self.calculate_price(data.room_id, data.check_in, data.check_out)

        booking = RoomBooking(
            room_id=data.room_id,
            merchant_id=data.merchant_id,
            client_id=data.client_id,
            guest_name=data.guest_name,
            guest_phone=data.guest_phone,
            check_in=data.check_in,
            check_out=data.check_out,
            total_amount=total_amount,
            status=BookingStatus.CREATED,
            source=data.source,
            logged_by_staff_phone=data.logged_by_staff_phone,
            raw_staff_message=data.raw_staff_message,
        )
        self.db.add(booking)
        await self.db.commit()
        await self.db.refresh(booking)
        return booking

    # -----------------------------
    # STAFF QUICK-LOG — the "text the room as booked" flow
    # -----------------------------
    async def staff_log_booking(
        self,
        merchant_id: str,
        client_id: str,
        room_id,
        nights: int,
        staff_phone: str,
        raw_message: str,
        guest_name: Optional[str] = None,
        check_in: Optional[date] = None,
    ) -> RoomBooking:
        """
        Staff typed something like "room 4 booked 3 nights" — by the time
        this is called, the inbound WhatsApp text has already been through
        LLM extraction + fuzzy room-number matching (see the staff WhatsApp
        handler, next phase). This method just takes the clean, structured
        result and writes it straight to PAID, since staff are reporting a
        booking that's already happened at the front desk, not asking us to
        collect payment.
        """
        from datetime import timezone, datetime as dt, timedelta
        effective_check_in = check_in or dt.now(timezone.utc).date()
        effective_check_out = effective_check_in + timedelta(days=nights)

        data = RoomBookingCreate(
            room_id=room_id,
            merchant_id=merchant_id,
            client_id=client_id,
            guest_name=guest_name,
            check_in=effective_check_in,
            check_out=effective_check_out,
            source=BookingSource.STAFF_WHATSAPP,
            logged_by_staff_phone=staff_phone,
            raw_staff_message=raw_message,
        )
        booking = await self.create_booking(data)
        await booking.transition_to(BookingStatus.PAID, self.db)
        booking.amount_paid = booking.total_amount
        await self.db.commit()
        await self.db.refresh(booking)
        return booking

    # -----------------------------
    # PAYMENT CONFIRMATION (called from the Flutterwave webhook handler)
    # -----------------------------
    async def confirm_payment(
        self, booking_id: str, payment_ref: str, amount_paid: Decimal
    ) -> RoomBooking:
        """
        booking_id may be either the internal UUID-string id or the
        8-character booking_code (Flutterwave's tx_ref should be set to
        the booking_code at payment-link creation time, so this is
        normally a booking_code lookup — see the webhook handler).
        """
        stmt = (
            select(RoomBooking)
            .where((RoomBooking.id == booking_id) | (RoomBooking.booking_code == booking_id))
            .with_for_update()
        )
        booking = (await self.db.execute(stmt)).scalars().first()

        if not booking:
            raise ValueError("Booking not found")

        # Re-check availability under lock — this is where a genuine double
        # booking (two guests both paid) would surface, per the tradeoff
        # noted in the class docstring.
        still_available = await RoomBooking.is_room_available(
            self.db, booking.room_id, booking.check_in, booking.check_out,
            exclude_booking_id=booking.id,
        )
        if not still_available:
            await booking.transition_to(BookingStatus.CANCELLED, self.db)
            await self.db.commit()
            raise BookingConflictError(
                "Room was booked by someone else before this payment confirmed. "
                "This booking has been cancelled — refund required."
            )

        booking.payment_ref = payment_ref
        booking.amount_paid = amount_paid
        await booking.transition_to(BookingStatus.PAID, self.db)
        await self.db.commit()
        await self.db.refresh(booking)
        return booking

    # -----------------------------
    # MANAGER-AUTHORIZED REVERT — bypasses the normal state machine
    # -----------------------------
    async def revert_booking_status(
        self, booking_id: str, target_status: BookingStatus, reverting_staff_id
    ) -> RoomBooking:
        """
        Deliberately separate from transition_to()/BookingStatus.can_transition_to().
        That state machine is intentionally strict for everyday use (e.g.
        CANCELLED has no outgoing transitions) — this method exists
        specifically for manager-authorized reverts of a StaffActionLog
        entry, and callers MUST have already verified the calling staff
        member has can_review_flagged_actions() permission before reaching
        here. This method itself does not check permissions — that's the
        caller's job (see StaffOrchestrator._handle_revert), same
        separation as everywhere else in this codebase between service
        (mechanism) and orchestrator (policy/permission).
        """
        stmt = select(RoomBooking).where(RoomBooking.id == booking_id).with_for_update()
        booking = (await self.db.execute(stmt)).scalars().first()
        if not booking:
            raise ValueError("Booking not found")

        from datetime import timezone as _tz, datetime as _dt
        booking.status = target_status
        booking.updated_at = _dt.now(_tz.utc)
        self.db.add(booking)
        await self.db.commit()
        await self.db.refresh(booking)
        return booking

    # -----------------------------
    # STATUS TRANSITIONS
    # -----------------------------
    async def check_in_guest(self, booking_id: str) -> RoomBooking:
        booking = await self._get_booking(booking_id)
        await booking.transition_to(BookingStatus.CHECKED_IN, self.db)
        await self.db.commit()
        await self.db.refresh(booking)
        return booking

    async def check_out_guest(self, booking_id: str) -> RoomBooking:
        booking = await self._get_booking(booking_id)
        await booking.transition_to(BookingStatus.CHECKED_OUT, self.db)
        await self.db.commit()
        await self.db.refresh(booking)
        return booking

    async def cancel_booking(self, booking_id: str) -> RoomBooking:
        booking = await self._get_booking(booking_id)
        await booking.transition_to(BookingStatus.CANCELLED, self.db)
        await self.db.commit()
        await self.db.refresh(booking)
        return booking

    async def _get_booking(self, booking_id: str) -> RoomBooking:
        stmt = select(RoomBooking).where(
            (RoomBooking.id == booking_id) | (RoomBooking.booking_code == booking_id)
        )
        booking = (await self.db.execute(stmt)).scalars().first()
        if not booking:
            raise ValueError("Booking not found")
        return booking
