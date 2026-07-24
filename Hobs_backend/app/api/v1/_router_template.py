import logging
logger = logging.getLogger(__name__)

# app/api/v1/_router_template.py
from fastapi import APIRouter, Depends, Request, status, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_tenant, get_db_session
from app.core.config import settings

router = APIRouter(tags=["example"])

@router.get("/health", status_code=status.HTTP_200_OK)
async def health():
    return {"status": "ok", "project": settings.PROJECT_NAME}

@router.get("/products")
async def list_products(tenant = Depends(get_tenant), db: AsyncSession = Depends(get_db_session)):
    """
    Example safe pattern for tenant-scoped endpoint.
    Replace the body with the existing logic from your inventory router.
    """
    merchant_id = tenant["merchant_id"]
    client_id = tenant.get("client_id")
    # call existing service (I will patch service to accept db, merchant_id, client_id)
    # from app.services.product_service import get_products_for_tenant
    # return await get_products_for_tenant(db, merchant_id, client_id)
    return {"detail": "Replace with actual service call", "merchant_id": merchant_id, "client_id": client_id}
