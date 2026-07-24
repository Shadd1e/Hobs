# app/models/__init__.py
#
# Every model class must be imported here so SQLAlchemy's Base.metadata
# knows about all tables. Alembic's env.py imports this module to
# auto-generate migrations.
#
# ORDER MATTERS for circular-import safety:
#   Base → scalar models → models with FK dependencies → junction/log models

from app.db.base import Base

# ── Core tenant models ────────────────────────────────────────────────────────
from app.models.merchant import Merchant
from app.models.merchant_application import MerchantApplication
from app.models.client_model   import Client

# ── Customer identity (cross-store, not tenant-scoped) ────────────────────────
from app.models.customer_profile import CustomerProfile

# ── Product catalogue ─────────────────────────────────────────────────────────
from app.models.product   import Product
from app.models.inventory import Inventory

# ── Shopping flow ─────────────────────────────────────────────────────────────
from app.models.cart    import Cart, CartItem
from app.models.order   import Order, OrderStatus, DeliveryType
from app.models.payment import Payment, PaymentStatus

# ── Hotel domain (HoBS) ────────────────────────────────────────────────────────
from app.models.room_type    import RoomType
from app.models.room         import Room
from app.models.room_booking import RoomBooking, BookingStatus, BookingSource
from app.models.hotel_staff  import HotelStaff

# ── WhatsApp / messaging ──────────────────────────────────────────────────────
from app.models.client_whatsapp_credential import ClientWhatsAppCredential
from app.models.webhook_event              import WebhookEvent
from app.models.whatsapp_message_log       import WhatsappMessageLog
from app.models.clarification              import Clarification
from app.models.human_agent                import HumanAgent

# ── Platform config ───────────────────────────────────────────────────────────
from app.models.deepseek_setting       import DeepSeekSetting
from app.models.idempotence            import IdempotencyKey
from app.models.flutterwave_subaccount import FlutterwaveSubaccount

# ── Public API of this package ────────────────────────────────────────────────
__all__ = [
    "Base",

    # Tenant
    "Merchant",
    "MerchantApplication",
    "Client",

    # Customer identity
    "CustomerProfile",

    # Catalogue
    "Product",
    "Inventory",

    # Shopping
    "Cart",
    "CartItem",
    "Order",
    "OrderStatus",
    "DeliveryType",
    "Payment",
    "PaymentStatus",

    # Hotel domain (HoBS)
    "RoomType",
    "Room",
    "RoomBooking",
    "BookingStatus",
    "BookingSource",
    "HotelStaff",

    # WhatsApp / messaging
    "ClientWhatsAppCredential",
    "WebhookEvent",
    "WhatsappMessageLog",
    "Clarification",
    "HumanAgent",

    # Platform config
    "DeepSeekSetting",
    "IdempotencyKey",
    "FlutterwaveSubaccount",
]
