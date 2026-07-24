from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.client_whatsapp_credential import ClientWhatsAppCredential
from app.core.tenant_context import TenantContext
from app.core.redis_client import get_cached_tenant, set_cached_tenant


async def resolve_tenant_by_phone_number_id(
    db: AsyncSession,
    phone_number_id: str,
) -> TenantContext:

    # ----------------------------
    # REDIS FIRST
    # ----------------------------
    cached = await get_cached_tenant(phone_number_id)

    if cached:
        return TenantContext(**cached)

    # ----------------------------
    # DATABASE FALLBACK
    # ----------------------------
    result = await db.execute(
        select(ClientWhatsAppCredential)
        .where(
            ClientWhatsAppCredential.phone_number_id == phone_number_id,
            ClientWhatsAppCredential.active.is_(True),
        )
        .options(selectinload(ClientWhatsAppCredential.client))
    )

    credential = result.scalars().first()

    if not credential or not credential.client:
        raise HTTPException(
            status_code=404,
            detail="Unknown WhatsApp phone_number_id or inactive client.",
        )

    client = credential.client

    tenant = TenantContext(
        merchant_id=client.merchant_id,
        client_id=client.id,
        phone_number_id=credential.phone_number_id,
        client_name=client.name,
        operator_notify_phone=client.operator_notify_phone,
        # Delivery settings
        delivery_enabled=bool(client.delivery_enabled),
        delivery_fee=client.delivery_fee,
        delivery_area=getattr(client, "delivery_area", None),
        # Assistant persona
        assistant_name=client.assistant_name,
        assistant_personality=client.assistant_personality,
        # Store hours
        opens_at=getattr(client, "opens_at", None),
        closes_at=getattr(client, "closes_at", None),
        store_timezone=getattr(client, "store_timezone", None) or "Africa/Lagos",
    )

    # ----------------------------
    # CACHE RESULT
    # Cache as dict — Decimal must be serialised to str to survive JSON round-trip
    # ----------------------------
    cache_dict = tenant.model_dump()
    if cache_dict.get("delivery_fee") is not None:
        cache_dict["delivery_fee"] = str(cache_dict["delivery_fee"])

    await set_cached_tenant(phone_number_id, cache_dict)

    return tenant
