# app/schemas/checkout.py

from typing import Optional, Literal
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional

class CheckoutRequestSchema(BaseModel):
    """
    Checkout input.

    NOTE:
    merchant_id, client_id, user_id should be injected by the router,
    not trusted from public body input.
    """

    merchant_id: Optional[str] = None
    client_id:   Optional[str] = None
    user_id:     Optional[str] = None

    cart_id: str = Field(..., description="Cart UUID")

    payment_method: Literal[
        "bank_transfer",
        "cash",
        "whatsapp_payment",
        "card",
        "wishlist",
    ]

    whatsapp_payment_details: Optional[dict] = None

    customer_name: Optional[str] = Field(None, max_length=100)
    store_contact_number: Optional[str] = None

    # ── Delivery ───────────────────────────────────────────────────────────────
    # "pickup" | "delivery" | None (None = not asked yet / store has no delivery)
    delivery_type: Optional[Literal["pickup", "delivery"]] = None

    # Full address string captured from WhatsApp conversation
    delivery_address: Optional[str] = Field(None, max_length=500)

    # Rider contact number — may differ from customer's WhatsApp number
    delivery_contact_number: Optional[str] = Field(None, max_length=20)

    # Flat delivery fee in local currency — snapshot from client.delivery_fee
    delivery_fee: Optional[float] = None

    # Legacy fields — kept for API compatibility
    pickup_location: Optional[str] = Field(None, max_length=255)
    notes:           Optional[str] = None

    model_config = ConfigDict(extra="forbid")


class CheckoutResponseSchema(BaseModel):
    success: bool

    order_id:     Optional[str] = None
    order_code:   Optional[str] = None
    order_status: Optional[str] = None   # uppercase enum value

    message: str

    total_amount:         Optional[float] = None
    payment_instructions: Optional[str]  = None
    estimated_time:       Optional[str]  = None
    store_contact:        Optional[str]  = None

    payment_link: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
