from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Optional
import logging

from app.db.session import get_db
from app.models.client_whatsapp_credential import ClientWhatsAppCredential
from app.models.client_model import Client
from app.schemas.client_whatsapp_credential import (
    ClientWhatsAppCredentialOut,
    ClientWhatsAppCredentialSummary,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/whatsapp-routing",
    tags=["WhatsApp Routing"],
)


@router.get(
    "/",
    response_model=List[ClientWhatsAppCredentialSummary],
    summary="List WhatsApp routing records",
    description="List WhatsApp phone number routing records for the merchant’s clients"
)
async def list_routing_records(
    request: Request,
    db: AsyncSession = Depends(get_db),
    active_only: bool = Query(True, description="Return only active routes"),
    client_id: Optional[str] = Query(None, description="Filter by client ID"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
):
    merchant_id = getattr(request.state, "merchant_id", None)
    if not merchant_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    stmt = (
        select(ClientWhatsAppCredential)
        .join(Client, ClientWhatsAppCredential.client_id == Client.id)
        .where(Client.merchant_id == merchant_id)
    )

    if active_only:
        stmt = stmt.where(ClientWhatsAppCredential.active.is_(True))

    if client_id:
        client_check = await db.execute(
            select(Client).where(
                Client.id == client_id,
                Client.merchant_id == merchant_id,
            )
        )
        if not client_check.scalars().first():
            raise HTTPException(status_code=403, detail="Client not found or not owned")

        stmt = stmt.where(ClientWhatsAppCredential.client_id == client_id)

    stmt = stmt.order_by(
        ClientWhatsAppCredential.created_at.desc()
    ).offset(skip).limit(limit)

    res = await db.execute(stmt)
    return res.scalars().all()


@router.get(
    "/by-client/{client_id}",
    response_model=ClientWhatsAppCredentialOut,
    summary="Get WhatsApp routing by client",
    description="Resolve WhatsApp routing details for a specific client"
)
async def get_routing_by_client(
    client_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    merchant_id = getattr(request.state, "merchant_id", None)
    if not merchant_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    client_check = await db.execute(
        select(Client).where(
            Client.id == client_id,
            Client.merchant_id == merchant_id,
        )
    )
    if not client_check.scalars().first():
        raise HTTPException(status_code=403, detail="Client not found or not owned")

    res = await db.execute(
        select(ClientWhatsAppCredential).where(
            ClientWhatsAppCredential.client_id == client_id,
            ClientWhatsAppCredential.active.is_(True),
        )
    )
    credential = res.scalars().first()

    if not credential:
        raise HTTPException(
            status_code=404,
            detail="No active WhatsApp routing found for this client",
        )

    return credential
