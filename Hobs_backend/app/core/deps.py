import logging
logger = logging.getLogger(__name__)

# app/core/deps.py
from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.db.deps import get_db
from app.core.tenant_resolver import resolve_tenant_by_phone_number_id
from app.core.tenant import TenantContext


async def get_tenant(
    db: AsyncSession = Depends(get_db),
    x_phone_number_id: Optional[str] = Header(None),
) -> TenantContext:
    if not x_phone_number_id:
        raise HTTPException(
            status_code=400,
            detail="X-Phone-Number-Id header is required",
        )

    return await resolve_tenant_by_phone_number_id(
        db=db,
        phone_number_id=x_phone_number_id,
    )
