from fastapi import APIRouter, HTTPException, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
import logging

from app.schemas.checkout import CheckoutRequestSchema, CheckoutResponseSchema
from app.services.checkout_service import CheckoutService
from app.services.idempotence_service import IdempotencyError
from app.db.deps import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/checkout", tags=["Checkout"])


@router.post("/", response_model=CheckoutResponseSchema)
async def checkout(
    request: Request,
    checkout_data: CheckoutRequestSchema,
    db: AsyncSession = Depends(get_db),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")
):
    checkout_service = CheckoutService(db)

    try:
        return await checkout_service.checkout(
            data=checkout_data,
            idempotency_key=idempotency_key
        )

    except IdempotencyError as e:
        msg = str(e)

        if msg == "CHECKOUT_IN_PROGRESS":
            raise HTTPException(409, "Checkout already processing")

        if msg == "IDEMPOTENCY_KEY_MISMATCH":
            raise HTTPException(400, "Idempotency key reused with different payload")

        raise HTTPException(409, msg)

    except ValueError as e:
        raise HTTPException(400, str(e))

    except Exception:
        logger.exception("Checkout failed")
        raise HTTPException(500, "Internal server error")