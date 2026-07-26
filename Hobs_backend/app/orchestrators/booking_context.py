# app/orchestrators/booking_context.py
from dataclasses import dataclass
from typing import Any, Optional
from app.core.tenant_context import TenantContext
from app.conversation.memory import ConversationMemory
from app.services.booking_service import BookingService
from app.services.room_type_service import RoomTypeService
from app.services.room_service import RoomService


@dataclass
class BookingContext:
    """
    Guest-conversation equivalent of ConversationContext (shop domain).
    TenantContext is reused as-is — client_id/client_name/operator_notify_phone/
    assistant persona all mean the same thing for a hotel as for a store;
    only delivery_* fields go unused here.
    """
    tenant: TenantContext
    db: Any
    user_phone: str
    user_text: str
    phone_number_id: str
    memory: ConversationMemory
    booking_service: BookingService
    room_type_service: RoomTypeService
    room_service: RoomService
