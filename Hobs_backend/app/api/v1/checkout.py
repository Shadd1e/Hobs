# app/api/v1/checkout.py

import logging
from fastapi import APIRouter, Depends, HTTPException, Header, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.db.deps import get_db
from app.schemas.checkout import CheckoutRequestSchema, CheckoutResponseSchema
from app.services.checkout_service import CheckoutService
from app.core.redis_client import rate_limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/checkout", tags=["Checkout"])


@router.post(
    "/{merchant_id}/{client_id}",
    response_model=CheckoutResponseSchema,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limiter("checkout", max_requests=20, window_seconds=60))],
)
async def create_checkout(
    merchant_id: str,
    client_id: str,
    data: CheckoutRequestSchema,
    request: Request,
    db: AsyncSession = Depends(get_db),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    """
    Tenant-scoped checkout endpoint.

    - merchant_id and client_id come strictly from path.
    - user_id must be provided in body.
    - Idempotency supported via header.
    """
    authed_id = getattr(request.state, "merchant_id", None)
    if not authed_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    if merchant_id != authed_id:
        raise HTTPException(status_code=403, detail="Access denied")

    # Enforce tenant isolation (never trust body for this)
    data = data.model_copy(
        update={
            "merchant_id": merchant_id,
            "client_id": client_id,
        }
    )

    if not data.user_id:
        raise HTTPException(
            status_code=400,
            detail="user_id is required in request body",
        )

    service = CheckoutService(db)

    try:
        response = await service.checkout(
            data=data,
            idempotency_key=idempotency_key,
        )
        return response

    except ValueError as e:
        logger.warning("Checkout ValueError: %s", e)
        raise HTTPException(
            status_code=400,
            detail="Unable to complete checkout. Please try again or contact support.",
        )

    except Exception as e:
        logger.exception("Checkout failed")
        raise HTTPException(
            status_code=500,
            detail="Checkout processing failed",
        )