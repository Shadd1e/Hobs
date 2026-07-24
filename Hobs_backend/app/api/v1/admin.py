# app/api/v1/admin.py
"""
WhatsApp credential management — merchant-scoped.
These endpoints are for reading/managing credentials for a merchant's own stores.
Protected by normal merchant JWT (not admin secret).
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import logging

from app.db.session import get_db
from app.models.client_whatsapp_credential import ClientWhatsAppCredential
from app.models.client_model import Client
from app.schemas.client_whatsapp_credential import (
    ClientWhatsAppCredentialCreate,
    ClientWhatsAppCredentialOut,
    ClientWhatsAppCredentialSummary,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/merchant-credentials",
    tags=["WhatsApp Credentials (Admin)"],
)


# ── Onboarding status constants (mirrors admin_whatsapp.py) ──────────────────
STATUS_PENDING         = "pending"
STATUS_ADDED_TO_WABA   = "added_to_waba"
STATUS_OTP_REQUESTED   = "otp_requested"
STATUS_OTP_SUBMITTED   = "otp_submitted"
STATUS_OTP_FAILED      = "otp_failed"
STATUS_NUMBER_IN_USE   = "number_in_use"
STATUS_NUMBER_PERSONAL = "number_personal"
STATUS_NUMBER_INVALID  = "number_invalid"
STATUS_ACTIVE          = "active"

# Statuses where number editing is permanently or temporarily blocked
_LOCKED_STATUSES = {STATUS_OTP_REQUESTED, STATUS_OTP_SUBMITTED, STATUS_ACTIVE}


def _require_merchant(request: Request) -> str:
    merchant_id = getattr(request.state, "merchant_id", None)
    if not merchant_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    return merchant_id


# ── CREATE CREDENTIAL ─────────────────────────────────────────────────────────
@router.post(
    "/",
    response_model=ClientWhatsAppCredentialOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_credential(
    payload: ClientWhatsAppCredentialCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    merchant_id = _require_merchant(request)

    # Verify client belongs to this merchant
    res = await db.execute(
        select(Client).where(
            Client.id == payload.client_id,
            Client.merchant_id == merchant_id,
        )
    )
    cl = res.scalars().first()
    if not cl:
        raise HTTPException(status_code=404, detail="Client not found under this merchant")

    # Block if store is locked
    current_status = getattr(cl, "onboarding_status", STATUS_PENDING)
    if current_status == STATUS_ACTIVE:
        raise HTTPException(
            status_code=403,
            detail="This store is already live. Contact support to make changes.",
        )

    # Enforce unique phone_number_id
    dup = await db.execute(
        select(ClientWhatsAppCredential).where(
            ClientWhatsAppCredential.phone_number_id == payload.phone_number_id
        )
    )
    if dup.scalars().first():
        raise HTTPException(status_code=400, detail="phone_number_id already registered")

    credential = ClientWhatsAppCredential(
        client_id=payload.client_id,
        phone_number_id=payload.phone_number_id,
        whatsapp_number=payload.whatsapp_number,
        active=True,
    )

    db.add(credential)
    await db.commit()
    await db.refresh(credential)

    logger.info(
        "WhatsApp credential created — merchant_id=%s client_id=%s",
        merchant_id, payload.client_id,
    )

    return credential


# ── LIST CREDENTIALS ──────────────────────────────────────────────────────────
@router.get("/", response_model=list[ClientWhatsAppCredentialSummary])
async def list_credentials(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    merchant_id = _require_merchant(request)

    res = await db.execute(
        select(ClientWhatsAppCredential)
        .join(Client, ClientWhatsAppCredential.client_id == Client.id)
        .where(Client.merchant_id == merchant_id)
        .order_by(ClientWhatsAppCredential.created_at.desc())
    )
    return res.scalars().all()


# ── GET BY CLIENT ─────────────────────────────────────────────────────────────
@router.get("/by-client/{client_id}", response_model=ClientWhatsAppCredentialOut)
async def get_credential_by_client(
    client_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    merchant_id = _require_merchant(request)

    res = await db.execute(
        select(ClientWhatsAppCredential)
        .join(Client)
        .where(
            ClientWhatsAppCredential.client_id == client_id,
            Client.merchant_id == merchant_id,
        )
    )
    cred = res.scalars().first()
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found")

    return cred


# ── GET ONBOARDING STATUS ─────────────────────────────────────────────────────
@router.get("/onboarding-status")
async def get_onboarding_status(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Returns the current onboarding status and whether the number
    is editable. Used by the merchant dashboard to show the right UI state.
    """
    merchant_id = _require_merchant(request)

    res = await db.execute(
        select(Client).where(Client.merchant_id == merchant_id)
    )
    cl = res.scalars().first()
    if not cl:
        raise HTTPException(status_code=404, detail="Store not found")

    current_status = getattr(cl, "onboarding_status", STATUS_PENDING)
    number_locked  = current_status in _LOCKED_STATUSES

    return {
        "onboarding_status": current_status,
        "whatsapp_number":   cl.whatsapp_number or "",
        "number_locked":     number_locked,
        "is_active":         current_status == STATUS_ACTIVE,
    }


# ── UPDATE CREDENTIAL ─────────────────────────────────────────────────────────
@router.put("/by-client/{client_id}", response_model=ClientWhatsAppCredentialOut)
async def update_credential(
    client_id: str,
    payload: ClientWhatsAppCredentialCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    merchant_id = _require_merchant(request)

    res = await db.execute(
        select(ClientWhatsAppCredential)
        .join(Client)
        .where(
            ClientWhatsAppCredential.client_id == client_id,
            Client.merchant_id == merchant_id,
        )
        .with_for_update()
    )
    cred = res.scalars().first()
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found")

    # Block updates on active stores
    client_res = await db.execute(select(Client).where(Client.id == client_id))
    cl = client_res.scalar_one_or_none()
    if cl and getattr(cl, "onboarding_status", None) == STATUS_ACTIVE:
        raise HTTPException(
            status_code=403,
            detail="Store is live. Contact support to make changes.",
        )

    cred.phone_number_id = payload.phone_number_id
    cred.whatsapp_number = payload.whatsapp_number
    cred.active          = payload.active

    await db.commit()
    await db.refresh(cred)

    return cred


# ── DEACTIVATE (SOFT DELETE) ──────────────────────────────────────────────────
@router.delete("/by-client/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_credential(
    client_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    merchant_id = _require_merchant(request)

    res = await db.execute(
        select(ClientWhatsAppCredential)
        .join(Client)
        .where(
            ClientWhatsAppCredential.client_id == client_id,
            Client.merchant_id == merchant_id,
        )
        .with_for_update()
    )
    cred = res.scalars().first()
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found")

    # Block deactivation on active stores
    client_res = await db.execute(select(Client).where(Client.id == client_id))
    cl = client_res.scalar_one_or_none()
    if cl and getattr(cl, "onboarding_status", None) == STATUS_ACTIVE:
        raise HTTPException(
            status_code=403,
            detail="Store is live. Contact support to deactivate.",
        )

    cred.active = False
    await db.commit()
