import logging
logger = logging.getLogger(__name__)

# app/api/v1/order_fulfillment.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.db.deps import get_db
from app.services.order_fulfillment_service import OrderFulfillmentService

router = APIRouter(prefix="/orders", tags=["Order Fulfillment"])


# -----------------------------------------
# REQUEST SCHEMA
# -----------------------------------------
class ConfirmPickupRequest(BaseModel):
    from_whatsapp_number: str


# -----------------------------------------
# CONFIRM CASH PICKUP
# -----------------------------------------
@router.post("/confirm-pickup/{order_code}")
async def confirm_pickup(
    order_code: str,
    payload: ConfirmPickupRequest,
    db: AsyncSession = Depends(get_db),
):
    service = OrderFulfillmentService(db)

    try:
        await service.confirm_pickup(
            order_code=order_code,
            from_whatsapp_number=payload.from_whatsapp_number,
        )
        return {
            "success": True,
            "message": "Order pickup confirmed and inventory updated",
        }

    except ValueError as e:
        logger.warning("confirm_pickup ValueError: %s", e)
        raise HTTPException(status_code=400, detail="Unable to process request. Please try again.")
