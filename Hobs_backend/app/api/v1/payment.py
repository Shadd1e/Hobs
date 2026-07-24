# app/api/v1/payments.py

import logging
from fastapi import APIRouter, HTTPException, Depends, status, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.payment import PaymentCreate, PaymentRead
from app.models.payment import PaymentStatus
from app.services.payment_service import PaymentService
from app.db.deps import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments", tags=["Payments"])


# -------------------------------------------------
# CREATE PAYMENT
# -------------------------------------------------

@router.post("/", response_model=PaymentRead, status_code=status.HTTP_201_CREATED)
async def create_payment_route(
    request: Request,
    payment: PaymentCreate,
    db: AsyncSession = Depends(get_db),
):
    _require_merchant(request)
    service = PaymentService(db)
    return await service.create(payment)


# -------------------------------------------------
# GET PAYMENT
# -------------------------------------------------

@router.get("/{payment_id}", response_model=PaymentRead)
async def get_payment_route(
    payment_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    _require_merchant(request)
    service = PaymentService(db)

    payment = await service.get(payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")

    return payment


# -------------------------------------------------
# UPDATE PAYMENT STATUS
# -------------------------------------------------

@router.put("/{payment_id}/status", response_model=PaymentRead)
async def update_payment_status_route(
    payment_id: str,
    new_status: PaymentStatus,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    _require_merchant(request)
    service = PaymentService(db)

    payment = await service.update_status(
        payment_id=payment_id,
        new_status=new_status,
    )

    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")

    return payment