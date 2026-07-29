import logging
logger = logging.getLogger(__name__)

# app/api/v1/api.py
from fastapi import APIRouter
from app.core.config import settings

from app.api.v1.webhook import router as webhook_router
from app.api.v1.hotel_webhook import router as hotel_webhook_router
from app.api.v1.inventory import router as inventory_router
from app.api.v1.payment import router as payment_router
from app.api.v1.auth import router as auth_router
from app.api.v1.merchant import router as merchant_router
from app.api.v1.product import router as product_router
from app.api.v1.client_api import router as client_router
from app.api.v1.cart import router as cart_router
from app.api.v1.checkout import router as checkout_router
from app.api.v1.orders_api import router as orders_router
from app.api.v1.order_fulfillment import router as order_fulfillment_router
from app.api.v1.human_agent import router as human_agent_router
from app.api.v1.admin import router as admin_router
from app.api.v1.credential import router as credential_router
from app.api.v1.client_whatsapp_credential import router as merchant_whatsapp_router
from app.api.v1.debug import router as debug_router


api_v1_router = APIRouter(prefix=settings.API_V1_STR)

api_v1_router.include_router(auth_router)
# Debug routes — auth enforced at router level via dependencies=[Depends(_require_merchant)]
api_v1_router.include_router(debug_router)
api_v1_router.include_router(merchant_router)
api_v1_router.include_router(client_router)
api_v1_router.include_router(product_router)
api_v1_router.include_router(inventory_router)
api_v1_router.include_router(cart_router)
api_v1_router.include_router(checkout_router)
api_v1_router.include_router(orders_router)
api_v1_router.include_router(order_fulfillment_router)
api_v1_router.include_router(payment_router)
api_v1_router.include_router(human_agent_router)
api_v1_router.include_router(admin_router)
api_v1_router.include_router(credential_router)
api_v1_router.include_router(merchant_whatsapp_router)
api_v1_router.include_router(webhook_router)
api_v1_router.include_router(hotel_webhook_router)