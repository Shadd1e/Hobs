from fastapi import APIRouter, HTTPException, Depends, Request, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from app.schemas.client_schema import (
    ClientCreate,
    ClientRead,
    ClientUpdate,
    ClientOut,
    ClientSummary,
    ClientWithCredentialCreate,
    ClientCreateWithPassword,
    ClientLoginRequest,
    ClientLoginResponse,
    ClientSetPassword,
)
from app.schemas.client_whatsapp_credential import (
    ClientWhatsAppCredentialCreate,
    ClientWhatsAppCredentialUpdate,
    ClientWhatsAppCredentialOut,
    ClientWhatsAppCredentialSimple,
)
from app.services.client_service import ClientService
from app.services.merchant_service import MerchantService
from app.core.security import create_client_access_token
from app.core.helpers import get_client_ip
from app.db.session import get_db
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/clients", tags=["Clients"])


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _require_merchant(request: Request) -> str:
    """Extract merchant_id from request.state or raise 401."""
    merchant_id = getattr(request.state, "merchant_id", None)
    if not merchant_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    return merchant_id


def _require_merchant_token(request: Request) -> str:
    """Requires a merchant (not client) token. Raises 403 for client tokens."""
    merchant_id = getattr(request.state, "merchant_id", None)
    if not merchant_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    if getattr(request.state, "token_type", "merchant") == "client":
        raise HTTPException(status_code=403, detail="Merchant account required for this action")
    return merchant_id


# ─────────────────────────────────────────────────────────────────────────────
# STORE LOGIN  (public — no auth)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/login", response_model=ClientLoginResponse)
async def store_login(
    payload: ClientLoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Store-scoped login. Takes client_id + password, returns a client JWT.
    The JWT embeds both client_id and merchant_id so all existing merchant-
    scoped endpoints keep working without changes.
    """
    from app.core.redis_client import check_login_rate_limit

    client_ip = get_client_ip(request)
    if not await check_login_rate_limit(client_ip, payload.client_id):
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts. Please wait 15 minutes before trying again.",
            headers={"Retry-After": "900"},
        )

    service = ClientService(db)
    client  = await service.authenticate(payload.client_id, payload.password)

    if not client:
        raise HTTPException(
            status_code=401,
            detail="Invalid Store ID or password",
        )

    # FIX: removed store_count < 2 gate — any store can log in regardless of how many
    # stores the merchant has. Single-store merchants should be able to use the store dashboard.

    # Notify merchant by email — fire-and-forget, non-fatal
    try:
        from sqlalchemy import select as _sel
        from app.models.merchant import Merchant as _M
        from app.services.email_service import send_store_login_alert
        _mres = await db.execute(_sel(_M).where(_M.id == client.merchant_id))
        _merchant = _mres.scalar_one_or_none()
        if _merchant and _merchant.email:
            import asyncio as _asyncio
            _asyncio.create_task(
                send_store_login_alert(
                    to_email=_merchant.email,
                    merchant_name=_merchant.name,
                    store_name=client.name or client.id,
                    client_id=client.id,
                )
            )
    except Exception as _notify_err:
        logger.warning("Store login notification failed (non-fatal): %s", _notify_err)

    token = create_client_access_token(
        client_id=client.id,
        merchant_id=client.merchant_id,
    )

    return ClientLoginResponse(
        access_token=token,
        token_type="bearer",
        client_id=client.id,
        store_name=client.name,
        merchant_id=client.merchant_id,
    )


# ─────────────────────────────────────────────────────────────────────────────
# CREATE STORE WITH PASSWORD  (merchant-auth required)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/with-password/", response_model=ClientOut)
async def create_client_with_password(
    payload: ClientCreateWithPassword,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Merchant creates a new store. The Store ID is auto-assigned by the system
    and sent to the merchant via email. A HoBS agent will contact the
    merchant to complete WhatsApp onboarding.
    """
    merchant_id = _require_merchant(request)

    # Verify merchant exists and grab their email for the notification
    merchant_service = MerchantService(db)
    merchant = await merchant_service.get(merchant_id)
    if not merchant:
        raise HTTPException(status_code=400, detail="Merchant not found")

    service = ClientService(db)

    # Reject if merchant already has a store with this exact name (case-insensitive)
    from sqlalchemy import select as _sa_select, func as _sa_func
    from app.models.client_model import Client as _ClientModel
    name_check = await db.execute(
        _sa_select(_ClientModel.id).where(
            _ClientModel.merchant_id == merchant_id,
            _sa_func.lower(_ClientModel.name) == payload.name.strip().lower(),
        )
    )
    if name_check.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail=f"You already have a store named \"{payload.name.strip()}\". Please choose a different name.",
        )

    client  = await service.create_with_password(merchant_id, payload)

    if not client:
        raise HTTPException(
            status_code=500,
            detail="Failed to create store. Please try again.",
        )

    # Fire-and-forget email notification — failure is non-fatal
    try:
        from app.services.email_service import send_store_created_email
        await send_store_created_email(
            merchant_email=merchant.email,
            store_name=client.name,
            client_id=client.id,
            whatsapp_number=client.whatsapp_number,
        )
    except Exception as e:
        logger.warning("Store-created email failed (non-fatal): %s", e)

    await db.refresh(client)
    return client


# ─────────────────────────────────────────────────────────────────────────────
# SET / RESET STORE PASSWORD  (merchant-auth required)
# ─────────────────────────────────────────────────────────────────────────────

@router.patch("/{client_id}/password")
async def set_store_password(
    client_id: str,
    payload: ClientSetPassword,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Merchant sets or resets a store's dashboard password.
    Only the owning merchant can call this.
    """
    merchant_id = _require_merchant(request)

    service = ClientService(db)
    client  = await service.set_password(
        client_id=client_id,
        password=payload.password,
        merchant_id=merchant_id,
    )

    if not client:
        raise HTTPException(status_code=404, detail="Store not found")

    return {"detail": "Password updated", "client_id": client.id}


# ─────────────────────────────────────────────────────────────────────────────
# EXISTING ENDPOINTS (unchanged)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/", response_model=ClientOut)
async def create_client(
    payload: ClientCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    merchant_id = _require_merchant(request)

    if payload.merchant_id != merchant_id:
        raise HTTPException(status_code=403, detail="Cannot create client for another merchant")

    merchant_service = MerchantService(db)
    merchant = await merchant_service.get(payload.merchant_id)
    if not merchant:
        raise HTTPException(status_code=400, detail=f"Merchant ID {payload.merchant_id} does not exist")

    service = ClientService(db)
    client  = await service.create(payload)
    if not client:
        raise HTTPException(status_code=400, detail="Client with this ID already exists")
    return client


@router.post("/with-credential/", response_model=ClientOut)
async def create_client_with_credential(
    payload: ClientWithCredentialCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    merchant_id = _require_merchant(request)

    if payload.client.merchant_id != merchant_id:
        raise HTTPException(status_code=403, detail="Cannot create client for another merchant")

    merchant_service = MerchantService(db)
    merchant = await merchant_service.get(payload.client.merchant_id)
    if not merchant:
        raise HTTPException(status_code=400, detail=f"Merchant ID {payload.client.merchant_id} does not exist")

    service = ClientService(db)
    client  = await service.create(payload.client)
    if not client:
        raise HTTPException(status_code=400, detail="Client with this ID already exists")

    if payload.credential:
        from sqlalchemy.future import select
        from app.models.client_whatsapp_credential import ClientWhatsAppCredential

        if payload.credential.client_id != client.id:
            raise HTTPException(status_code=400, detail="Credential client_id must match client ID")

        existing_phone = await db.execute(
            select(ClientWhatsAppCredential).where(
                ClientWhatsAppCredential.phone_number_id == payload.credential.phone_number_id
            )
        )
        if existing_phone.scalars().first():
            raise HTTPException(status_code=400, detail="WhatsApp phone number ID already registered")

        if payload.credential.whatsapp_number:
            existing_whatsapp = await db.execute(
                select(ClientWhatsAppCredential).where(
                    ClientWhatsAppCredential.whatsapp_number == payload.credential.whatsapp_number
                )
            )
            if existing_whatsapp.scalars().first():
                raise HTTPException(status_code=400, detail="WhatsApp number already registered")

        cred_data   = payload.credential.model_dump()
        credential  = ClientWhatsAppCredential(**cred_data)
        db.add(credential)
        await db.commit()
        await db.refresh(credential)

    await db.refresh(client)
    return client


@router.get("/checklist-status")
async def get_checklist_status(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Returns the real setup completion status for the merchant's first store.
    Used by the dashboard setup checklist — reads live DB state, no caching.
    """
    merchant_id = _require_merchant(request)

    from sqlalchemy import select, func
    from app.models.client_model import Client
    from app.models.client_whatsapp_credential import ClientWhatsAppCredential
    from app.models.product import Product
    from app.models.flutterwave_subaccount import FlutterwaveSubaccount

    result = await db.execute(
        select(Client).where(Client.merchant_id == merchant_id).order_by(Client.created_at).limit(1)
    )
    client = result.scalar_one_or_none()

    if not client:
        return {
            "has_store":    False,
            "has_products": False,
            "has_operator": False,
            "has_bank":     False,
            "waba_active":  False,
        }

    client_id = client.id

    prod_result = await db.execute(
        select(func.count(Product.id)).where(
            Product.merchant_id == merchant_id,
            Product.client_id   == client_id,
        )
    )
    has_products = (prod_result.scalar() or 0) > 0

    has_operator = bool(client.operator_notify_phone)

    bank_result = await db.execute(
        select(FlutterwaveSubaccount).where(
            FlutterwaveSubaccount.client_id   == client_id,
            FlutterwaveSubaccount.merchant_id == merchant_id,
            FlutterwaveSubaccount.active.is_(True),
        )
    )
    has_bank = bank_result.scalar_one_or_none() is not None

    cred_result = await db.execute(
        select(ClientWhatsAppCredential).where(
            ClientWhatsAppCredential.client_id == client_id,
            ClientWhatsAppCredential.active.is_(True),
        )
    )
    cred       = cred_result.scalar_one_or_none()
    waba_active = cred is not None and bool(getattr(cred, "phone_number_id", None))

    return {
        "has_store":    True,
        "has_products": has_products,
        "has_operator": has_operator,
        "has_bank":     has_bank,
        "waba_active":  waba_active,
    }


@router.get("/me")
async def get_my_store(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Store-scoped: returns the authenticated store's own client record.
    Returns a plain dict to avoid Pydantic validation dropping null fields.
    """
    merchant_id = _require_merchant(request)
    client_id   = getattr(request.state, "client_id", None)
    if not client_id:
        raise HTTPException(status_code=403, detail="Store token required")
    service = ClientService(db)
    client  = await service.get(client_id=client_id, merchant_id=merchant_id, include_credential=True)
    if not client:
        raise HTTPException(status_code=404, detail="Store not found")
    return {
        "id":                     client.id,
        "name":                   client.name,
        "merchant_id":            client.merchant_id,
        "whatsapp_number":        client.whatsapp_number,
        "store_contact_number":   client.store_contact_number,
        "operator_notify_phone":  client.operator_notify_phone,
        "address":                client.address,
        "assistant_name":         client.assistant_name,
        "assistant_personality":  client.assistant_personality,
        "delivery_enabled":       client.delivery_enabled,
        "delivery_fee":           float(client.delivery_fee) if client.delivery_fee is not None else None,
        "has_login":              client.has_login,
        "client_changes_enabled": client.client_changes_enabled,
    }


@router.get("/{client_id}", response_model=ClientOut)
async def get_client(
    client_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    merchant_id = _require_merchant(request)
    service = ClientService(db)
    client  = await service.get(client_id=client_id, merchant_id=merchant_id, include_credential=True)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


@router.get("/", response_model=List[ClientSummary])
async def list_clients(
    request: Request,
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    has_credential: Optional[bool] = Query(None),
):
    merchant_id = _require_merchant(request)
    service = ClientService(db)
    clients = await service.list_all(
        merchant_id=merchant_id,
        skip=skip,
        limit=limit,
        has_credential=has_credential,
    )
    return clients


@router.put("/{client_id}", response_model=ClientOut)
async def update_client(
    client_id: str,
    payload: ClientUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    merchant_id = _require_merchant(request)
    service = ClientService(db)
    updated = await service.update(client_id=client_id, payload=payload, merchant_id=merchant_id)
    if not updated:
        raise HTTPException(status_code=404, detail="Client not found or update failed")
    await db.refresh(updated)
    return updated


@router.delete("/{client_id}")
async def delete_client(
    client_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    merchant_id = _require_merchant(request)
    service = ClientService(db)
    deleted = await service.delete(client_id=client_id, merchant_id=merchant_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Client not found or could not be deleted")
    return {"detail": "Client deleted successfully"}


@router.patch("/{client_id}/operator-phone")
async def set_operator_notify_phone(
    client_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Set the operator WhatsApp number for this store.
    Body: {"operator_notify_phone": "2348012345678"}
    Set to null to disable notifications.
    """
    merchant_id = _require_merchant(request)

    body  = await request.json()
    phone = body.get("operator_notify_phone")

    if phone:
        from sqlalchemy import select as sa_select
        from app.models.client_model import Client as ClientModel
        normalized = phone.replace("+", "").strip()
        existing = await db.execute(
            sa_select(ClientModel).where(
                ClientModel.operator_notify_phone == normalized,
                ClientModel.id != client_id,
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=400,
                detail=(
                    f"This number ({normalized}) is already registered as an operator "
                    "for another store. Each number can only be linked to one store."
                ),
            )
        phone = normalized

    service = ClientService(db)

    # Capture whether this is a first-time set (was null before)
    from sqlalchemy import select as sa_select2
    from app.models.client_model import Client as ClientModel2
    existing_client_res = await db.execute(
        sa_select2(ClientModel2).where(ClientModel2.id == client_id)
    )
    existing_client = existing_client_res.scalar_one_or_none()
    is_first_time = (
        existing_client is not None
        and not existing_client.operator_notify_phone
        and phone is not None
    )

    updated = await service.update(
        client_id=client_id,
        payload=ClientUpdate(operator_notify_phone=phone),
        merchant_id=merchant_id,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Client not found")

    # ── Bust the Redis tenant cache ────────────────────────────────────────
    # The tenant context (including operator_notify_phone) is cached against
    # the store's WhatsApp phone_number_id. If we don't invalidate it here,
    # the operator's first message after setting their number will still see
    # the old cached tenant (operator_notify_phone = None) and fall through
    # to the customer shopping flow instead of the operator command handler.
    try:
        from app.core.redis_client import invalidate_tenant_cache
        from app.models.client_whatsapp_credential import ClientWhatsAppCredential
        from sqlalchemy import select as _sa_cred_select
        cred_res = await db.execute(
            _sa_cred_select(ClientWhatsAppCredential).where(
                ClientWhatsAppCredential.client_id == client_id,
                ClientWhatsAppCredential.active.is_(True),
            )
        )
        cred = cred_res.scalar_one_or_none()
        if cred:
            await invalidate_tenant_cache(cred.phone_number_id)
            logger.info(
                "Tenant cache busted for client_id=%s phone_number_id=%s",
                client_id, cred.phone_number_id,
            )
    except Exception as _cache_err:
        logger.warning("Tenant cache invalidation failed (non-fatal): %s", _cache_err)

    # Fire Slack alert only on first-time operator number set — this is the
    # onboarding trigger. Admin sees it and reaches out to the merchant.
    if is_first_time:
        try:
            from app.infrastructure.alerting.slack import alert
            from app.services.merchant_service import MerchantService as _MS
            _merchant = await _MS(db).get(merchant_id)
            from app.api.v1.workers.background_tasks import fire_and_forget
            fire_and_forget(alert(
                title="Merchant Ready for Onboarding",
                detail=(
                    f"*{_merchant.name if _merchant else merchant_id}* just set their operator number. "
                    f"Time to reach out and complete WhatsApp activation."
                ),
                level="info",
                fields={
                    "Merchant ID":      merchant_id,
                    "Email":            _merchant.email if _merchant else "—",
                    "Store ID":         client_id,
                    "Store WA Number":  updated.whatsapp_number or "Not submitted",
                    "Operator Number":  f"+{phone}",
                },
            ))
        except Exception as _e:
            logger.warning("Onboarding Slack alert failed (non-fatal): %s", _e)

    return {
        "detail": "Operator notification phone updated",
        "operator_notify_phone": updated.operator_notify_phone,
    }


@router.patch("/{client_id}/rename")
async def rename_store(
    client_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    merchant_id = _require_merchant(request)

    body = await request.json()
    name = (body.get("name") or "").strip()

    if not name:
        raise HTTPException(status_code=400, detail="Store name cannot be empty")
    if len(name) > 100:
        raise HTTPException(status_code=400, detail="Store name must be 100 characters or fewer")

    service = ClientService(db)
    client  = await service.get(client_id, merchant_id=merchant_id, include_credential=False)
    if not client:
        raise HTTPException(status_code=404, detail="Store not found")

    client.name = name
    await db.commit()
    await db.refresh(client)

    return {"detail": "Store renamed", "id": client.id, "name": client.name}


@router.patch("/{client_id}/address")
async def set_store_address(
    client_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Set or clear the store address shown on PDF receipts."""
    merchant_id = _require_merchant(request)

    body        = await request.json()
    address_val = body.get("address", None)

    service = ClientService(db)
    updated = await service.update(
        client_id=client_id,
        payload=ClientUpdate(address=address_val),
        merchant_id=merchant_id,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Store not found")

    return {"detail": "Address saved", "address": updated.address}


@router.patch("/{client_id}/client-permissions")
async def set_client_permissions(
    client_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Merchant toggles whether a store can edit its own delivery/persona settings.
    Body: {"client_changes_enabled": true | false}
    Only merchant tokens may call this.
    """
    merchant_id = _require_merchant_token(request)

    body    = await request.json()
    enabled = body.get("client_changes_enabled")

    if enabled is None:
        raise HTTPException(status_code=422, detail="client_changes_enabled (bool) is required")

    from sqlalchemy import select as _sel
    from app.models.client_model import Client as _CM
    res = await db.execute(_sel(_CM).where(_CM.id == client_id, _CM.merchant_id == merchant_id))
    client = res.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Store not found")

    client.client_changes_enabled = bool(enabled)
    await db.commit()

    return {
        "detail": "Permissions updated",
        "client_id": client_id,
        "client_changes_enabled": client.client_changes_enabled,
    }


VALID_PERSONALITIES = {"friendly_casual", "professional", "warm_enthusiastic"}


@router.patch("/{client_id}/persona")
async def set_assistant_persona(
    client_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Set or clear the WhatsApp assistant persona for a store.
    Accepts: { assistant_name: str|null, assistant_personality: str|null }
    Invalidates the Redis tenant cache so the change takes effect immediately.
    """
    from app.core.redis_client import invalidate_tenant_cache
    from sqlalchemy import select
    from app.models.client_whatsapp_credential import ClientWhatsAppCredential

    merchant_id = _require_merchant(request)

    body                  = await request.json()
    assistant_name        = body.get("assistant_name") or None
    assistant_personality = body.get("assistant_personality") or None

    if assistant_personality and assistant_personality not in VALID_PERSONALITIES:
        raise HTTPException(
            status_code=422,
            detail=f"assistant_personality must be one of: {', '.join(sorted(VALID_PERSONALITIES))}",
        )

    if assistant_name:
        assistant_name = assistant_name.strip()[:80] or None

    service = ClientService(db)
    updated = await service.update(
        client_id=client_id,
        payload=ClientUpdate(
            assistant_name=assistant_name,
            assistant_personality=assistant_personality,
        ),
        merchant_id=merchant_id,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Store not found")

    try:
        cred_result = await db.execute(
            select(ClientWhatsAppCredential).where(
                ClientWhatsAppCredential.client_id == client_id,
                ClientWhatsAppCredential.active.is_(True),
            )
        )
        cred = cred_result.scalar_one_or_none()
        if cred:
            await invalidate_tenant_cache(cred.phone_number_id)
    except Exception as cache_err:
        logger.warning("Tenant cache invalidation failed (non-fatal): %s", cache_err)

    return {
        "detail":               "Persona saved",
        "assistant_name":        updated.assistant_name,
        "assistant_personality": updated.assistant_personality,
    }


# ─────────────────────────────────────────────────────────────────────────────
# DELIVERY SETTINGS  (merchant-auth required)
# ─────────────────────────────────────────────────────────────────────────────

@router.patch("/{client_id}/delivery")
async def set_delivery_settings(
    client_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Enable/disable delivery and set the flat delivery fee for a store.

    Body:
      {
        "delivery_enabled": true | false,
        "delivery_fee": 1500.00        # required when enabling delivery
      }

    - delivery_enabled=true without a delivery_fee raises a 422.
    - delivery_enabled=false clears the fee check but preserves the stored fee.
    - Invalidates the Redis tenant cache so the conversation picks up the
      change immediately (non-fatal if cache is unavailable).
    """
    from app.core.redis_client import invalidate_tenant_cache
    from sqlalchemy import select
    from app.models.client_whatsapp_credential import ClientWhatsAppCredential

    merchant_id = _require_merchant(request)

    body             = await request.json()
    delivery_enabled = body.get("delivery_enabled")
    delivery_fee     = body.get("delivery_fee")

    if delivery_enabled is None:
        raise HTTPException(status_code=422, detail="delivery_enabled is required")

    if delivery_enabled and (delivery_fee is None or float(delivery_fee) < 0):
        raise HTTPException(
            status_code=422,
            detail="A delivery_fee (≥ 0) is required when enabling delivery",
        )

    update_payload = ClientUpdate(
        delivery_enabled=bool(delivery_enabled),
        delivery_fee=float(delivery_fee) if delivery_fee is not None else None,
    )

    service = ClientService(db)
    updated = await service.update(
        client_id=client_id,
        payload=update_payload,
        merchant_id=merchant_id,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Store not found")

    # Invalidate Redis tenant cache so the WhatsApp conversation picks up the change
    try:
        cred_result = await db.execute(
            select(ClientWhatsAppCredential).where(
                ClientWhatsAppCredential.client_id == client_id,
                ClientWhatsAppCredential.active.is_(True),
            )
        )
        cred = cred_result.scalar_one_or_none()
        if cred:
            await invalidate_tenant_cache(cred.phone_number_id)
    except Exception as cache_err:
        logger.warning("Tenant cache invalidation after delivery update failed (non-fatal): %s", cache_err)

    return {
        "detail":           "Delivery settings saved",
        "delivery_enabled": updated.delivery_enabled,
        "delivery_fee":     float(updated.delivery_fee) if updated.delivery_fee is not None else None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# WHATSAPP CREDENTIAL ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/{client_id}/whatsapp-credential", response_model=ClientWhatsAppCredentialOut)
async def create_client_credential(
    client_id: str,
    payload: ClientWhatsAppCredentialCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    merchant_id = _require_merchant(request)
    service = ClientService(db)
    client  = await service.get(client_id=client_id, merchant_id=merchant_id, include_credential=True)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    if payload.client_id != client_id:
        raise HTTPException(status_code=400, detail="Client ID in payload must match URL parameter")
    if client.whatsapp_credential:
        raise HTTPException(status_code=400, detail="Client already has a WhatsApp credential")

    credential = await service.create_credential(
        client_id=client_id,
        credential_data=payload.model_dump(),
        merchant_id=merchant_id,
    )
    if not credential:
        raise HTTPException(status_code=400, detail="Failed to create credential. It may already exist or have duplicate data.")
    return credential


@router.get("/{client_id}/whatsapp-credential", response_model=ClientWhatsAppCredentialOut)
async def get_client_credential(
    client_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    merchant_id = _require_merchant(request)
    service     = ClientService(db)
    credential  = await service.get_credential(client_id=client_id, merchant_id=merchant_id)
    if not credential:
        raise HTTPException(status_code=404, detail="Client has no WhatsApp credential")
    return credential


@router.put("/{client_id}/whatsapp-credential", response_model=ClientWhatsAppCredentialOut)
async def update_client_credential(
    client_id: str,
    payload: ClientWhatsAppCredentialUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    merchant_id = _require_merchant(request)
    service     = ClientService(db)
    credential  = await service.update_credential(
        client_id=client_id,
        credential_data=payload.model_dump(exclude_unset=True),
        merchant_id=merchant_id,
    )
    if not credential:
        raise HTTPException(status_code=404, detail="Credential not found or update failed (check for duplicates)")
    return credential


@router.delete("/{client_id}/whatsapp-credential")
async def delete_client_credential(
    client_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    merchant_id = _require_merchant(request)
    service     = ClientService(db)
    deleted     = await service.delete_credential(client_id=client_id, merchant_id=merchant_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Credential not found or could not be deleted")
    return {"detail": "WhatsApp credential deleted successfully"}
