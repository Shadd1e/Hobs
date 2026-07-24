from pydantic import BaseModel
from typing import Optional
from decimal import Decimal


class TenantContext(BaseModel):
    merchant_id: str
    client_id: Optional[str] = None
    phone_number_id: Optional[str] = None
    client_name: Optional[str] = None
    operator_notify_phone: Optional[str] = None

    # ── Delivery settings ──────────────────────────────────────────────────────
    delivery_enabled: bool = False
    delivery_fee: Optional[Decimal] = None  # None = not configured yet
    delivery_area: Optional[str] = None    # e.g. "Port Harcourt" — shown in coverage notices

    # ── Assistant persona ──────────────────────────────────────────────────────
    assistant_name: Optional[str] = None
    assistant_personality: Optional[str] = None  # friendly_casual | professional | warm_enthusiastic

    # ── Store hours ────────────────────────────────────────────────────────────
    opens_at: Optional[str] = None        # "09:00" 24hr — None means always open
    closes_at: Optional[str] = None       # "21:00" 24hr — None means always open
    store_timezone: str = "Africa/Lagos"  # IANA timezone

    # ── Computed helpers ───────────────────────────────────────────────────────
    @property
    def delivery_ready(self) -> bool:
        """True only when delivery is both enabled AND a fee has been set."""
        return self.delivery_enabled and self.delivery_fee is not None

    @property
    def persona_name(self) -> str:
        return self.assistant_name or f"{self.client_name or self.client_id} Assistant"

    @property
    def persona_style(self) -> str:
        valid = {"friendly_casual", "professional", "warm_enthusiastic"}
        if self.assistant_personality in valid:
            return self.assistant_personality
        return "friendly_casual"
