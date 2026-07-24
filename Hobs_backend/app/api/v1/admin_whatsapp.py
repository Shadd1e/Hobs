# app/api/v1/admin_whatsapp.py
"""
Internal admin tool — WhatsApp number onboarding.
Protected by ADMIN_SECRET env var (Redis-backed session, 4 h expiry).
Accessible at /admin/whatsapp-setup

Merchant-facing self-serve endpoints live at the bottom under `merchant_router`
and are protected by the normal merchant JWT — not the admin secret.
"""

import os
import re
import secrets
import logging
import httpx

from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.deps import get_db
from app.core.helpers import get_client_ip

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/whatsapp-setup", tags=["Admin — WhatsApp Setup"])

GRAPH_URL = "https://graph.facebook.com/v20.0"

# ── Onboarding status constants ───────────────────────────────────────────────

STATUS_PENDING          = "pending"
STATUS_NUMBER_SUBMITTED = "number_submitted"
STATUS_ADDED_TO_WABA    = "added_to_waba"
STATUS_OTP_REQUESTED    = "otp_requested"
STATUS_OTP_SUBMITTED    = "otp_submitted"
STATUS_OTP_FAILED       = "otp_failed"
STATUS_NUMBER_IN_USE    = "number_in_use"
STATUS_NUMBER_PERSONAL  = "number_personal"
STATUS_NUMBER_INVALID   = "number_invalid"
STATUS_ACTIVE           = "active"

_LOCKED_STATUSES = {
    STATUS_OTP_REQUESTED,
    STATUS_OTP_SUBMITTED,
    STATUS_ACTIVE,
}

# ── Meta error mappings ───────────────────────────────────────────────────────

_META_ERROR_STATUS = {
    2388023: STATUS_NUMBER_IN_USE,
    2388094: STATUS_NUMBER_IN_USE,
    2388055: STATUS_NUMBER_PERSONAL,
    100:     STATUS_NUMBER_INVALID,
    200:     STATUS_NUMBER_INVALID,
    368:     STATUS_NUMBER_INVALID,
}

_META_ERROR_MESSAGE = {
    STATUS_NUMBER_IN_USE: (
        "This number is already registered on WhatsApp Business. "
        "If it's yours, remove it from that account first. "
        "Contact support if you need help."
    ),
    STATUS_NUMBER_PERSONAL: (
        "This number is currently active on a personal WhatsApp account. "
        "Delete your WhatsApp account on this number first, then come back and try again. "
        "Use the guide on the setup page to do this correctly."
    ),
    STATUS_NUMBER_INVALID: (
        "Meta couldn't recognise this number. "
        "Double-check it includes your country code and try again. "
        "If the problem persists, contact support."
    ),
}

# ── Local number validation ───────────────────────────────────────────────────

_VOIP_PREFIXES = ("1900", "1800", "1600", "1700")


def _normalise_number(raw: str) -> str:
    return re.sub(r"\D", "", raw)


def _validate_number_local(digits: str):
    if not digits:
        return "Please enter your phone number."
    if len(digits) < 7:
        return "That number is too short. Include your country code."
    if len(digits) > 15:
        return "That number is too long. Check for extra digits."
    if digits.startswith("0"):
        return (
            "Looks like you've entered a local number starting with 0. "
            "Include your country code — e.g. 2348012345678 instead of 08012345678."
        )
    if len(set(digits)) == 1:
        return "That doesn't look like a real phone number."
    if digits in ("123456789", "1234567890", "12345678901234"):
        return "That doesn't look like a real phone number."
    for prefix in _VOIP_PREFIXES:
        if digits.startswith(prefix):
            return (
                "This looks like a toll-free or VoIP number. "
                "ShopprHQ requires a regular mobile number that can receive SMS or calls."
            )
    return None


def _parse_meta_error(data: dict):
    err  = data.get("error", {})
    code = err.get("code", 0)
    msg  = err.get("message", str(data))
    return code, msg


def _merchant_message_for_meta_error(data: dict) -> str:
    meta_code, _ = _parse_meta_error(data)
    mapped_status = _META_ERROR_STATUS.get(meta_code)
    if mapped_status and mapped_status in _META_ERROR_MESSAGE:
        return _META_ERROR_MESSAGE[mapped_status]
    sub_code = data.get("error", {}).get("error_subcode", 0)
    if sub_code == 2388001:
        return (
            "This number is already verified on WhatsApp Business API. "
            "Contact support if this is your number."
        )
    if sub_code == 2388007:
        return "This number has been blocked from registration by Meta. Contact support."
    return (
        f"We couldn't complete this step right now ({meta_code}). "
        "Please try again or contact support if this keeps happening."
    )


# ── Config ────────────────────────────────────────────────────────────────────

def _cfg() -> dict:
    return {
        "admin_secret": os.getenv("ADMIN_SECRET", ""),
        "system_token": os.getenv("META_SYSTEM_TOKEN", ""),
        "waba_id":      os.getenv("META_WABA_ID", ""),
        "app_url":      os.getenv("APP_URL", "https://shopprhq.com"),
        "verify_token": os.getenv("META_VERIFY_TOKEN", ""),
    }


# ── Session guard ─────────────────────────────────────────────────────────────

async def _require_admin(request: Request):
    from app.core.redis_client import validate_admin_session
    token = request.headers.get("X-Admin-Token", "")
    if not token or not await validate_admin_session(token):
        raise HTTPException(status_code=401, detail="Unauthorized")


# ── Serve admin HTML ──────────────────────────────────────────────────────────
# RETIRED (this endpoint used to serve templates/admin_whatsapp.html directly).
# The Next.js frontend's /admin page is now the single admin panel — same
# backend endpoints, kept in sync, one URL to bookmark. This redirects any
# old links/bookmarks there instead of serving the stale duplicate UI.

@router.get("")
async def serve_admin_page():
    app_url = os.getenv("APP_URL", "https://shopprhq.com").rstrip("/")
    return RedirectResponse(url=f"{app_url}/admin", status_code=308)


# ── AUTH ──────────────────────────────────────────────────────────────────────

@router.post("/verify-password")
async def verify_password(request: Request):
    from app.core.redis_client import check_admin_rate_limit, create_admin_session
    client_ip = get_client_ip(request)
    if not await check_admin_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="Too many attempts — try again in 5 minutes.")
    body = await request.json()
    cfg  = _cfg()
    if not cfg["admin_secret"]:
        raise HTTPException(status_code=500, detail="ADMIN_SECRET not set in Railway variables")
    if body.get("password", "") != cfg["admin_secret"]:
        return {"ok": False}
    token = secrets.token_urlsafe(32)
    await create_admin_session(token)
    logger.info("Admin session created — ip=%s", client_ip)
    return {"ok": True, "token": token}


# ── LIST CLIENTS ──────────────────────────────────────────────────────────────

@router.get("/clients")
async def list_clients(request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin(request)
    from app.models.client_model import Client
    from app.models.merchant import Merchant
    result = await db.execute(
        select(Client, Merchant)
        .join(Merchant, Client.merchant_id == Merchant.id)
        .order_by(Merchant.name, Client.name)
    )
    rows = result.all()
    return {
        "clients": [
            {
                "id":                    c.id,
                "store_name":            c.name,
                "merchant_name":         m.name,
                "merchant_id":           m.id,
                "merchant_email":        m.email,
                "whatsapp_number":       c.whatsapp_number or "",
                "operator_notify_phone": c.operator_notify_phone or "",
                "onboarding_status":     getattr(c, "onboarding_status", STATUS_PENDING),
                "pending_otp_code":      getattr(c, "pending_otp_code", None),
            }
            for c, m in rows
        ]
    }


# ── STEP 1: Add number to WABA ────────────────────────────────────────────────

@router.post("/add-number")
async def add_number(request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin(request)
    body      = await request.json()
    phone     = _normalise_number(str(body.get("phone", "")))
    name      = str(body.get("display_name", "")).strip()
    client_id = str(body.get("client_id", "")).strip()
    cfg       = _cfg()
    client_ip = get_client_ip(request)
    logger.info("AUDIT add_number — ip=%s phone=%s client_id=%s", client_ip, phone, client_id)

    if not phone or not name:
        raise HTTPException(status_code=400, detail="Phone number and display name are required")
    local_err = _validate_number_local(phone)
    if local_err:
        raise HTTPException(status_code=400, detail=local_err)
    if not cfg["system_token"]:
        raise HTTPException(status_code=500, detail="META_SYSTEM_TOKEN not set")
    if not cfg["waba_id"]:
        raise HTTPException(status_code=500, detail="META_WABA_ID not set")

    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            f"{GRAPH_URL}/{cfg['waba_id']}/phone_numbers",
            headers={"Authorization": f"Bearer {cfg['system_token']}"},
            json={
                "cc":                   phone[:3] if len(phone) > 10 else "234",
                "phone_number":         phone,
                "display_name":         name,
                "migrate_phone_number": False,
            },
        )
    data = res.json()
    logger.info("Add number response: %s", data)

    if res.status_code not in (200, 201) or "id" not in data:
        mapped_status = _META_ERROR_STATUS.get(_parse_meta_error(data)[0])
        if client_id and mapped_status:
            await _set_client_status(db, client_id, mapped_status)
        raise HTTPException(status_code=400, detail=_merchant_message_for_meta_error(data))

    if client_id:
        await _set_client_status(db, client_id, STATUS_ADDED_TO_WABA)
    return {"phone_number_id": data["id"], "phone": phone}


# ── STEP 2: Request OTP ───────────────────────────────────────────────────────

@router.post("/request-otp")
async def request_otp(request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin(request)
    body            = await request.json()
    phone_number_id = str(body.get("phone_number_id", "")).strip()
    method          = str(body.get("method", "SMS")).strip().upper()
    client_id       = str(body.get("client_id", "")).strip()
    cfg             = _cfg()
    client_ip       = get_client_ip(request)
    logger.info("AUDIT request_otp — ip=%s phone_number_id=%s client_id=%s", client_ip, phone_number_id, client_id)

    if not phone_number_id:
        raise HTTPException(status_code=400, detail="phone_number_id required")
    if method not in ("SMS", "VOICE"):
        method = "SMS"

    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            f"{GRAPH_URL}/{phone_number_id}/request_code",
            headers={"Authorization": f"Bearer {cfg['system_token']}"},
            json={"code_method": method, "language": "en_US"},
        )
    data = res.json()
    logger.info("Request OTP response: %s", data)

    if res.status_code != 200 or not data.get("success"):
        mapped_status = _META_ERROR_STATUS.get(_parse_meta_error(data)[0])
        if client_id and mapped_status:
            await _set_client_status(db, client_id, mapped_status)
        raise HTTPException(status_code=400, detail=_merchant_message_for_meta_error(data))

    if client_id:
        await _set_client_status(db, client_id, STATUS_OTP_REQUESTED)

    if client_id:
        try:
            from app.models.client_model import Client
            from app.models.merchant import Merchant
            client_res = await db.execute(
                select(Client, Merchant)
                .join(Merchant, Client.merchant_id == Merchant.id)
                .where(Client.id == client_id)
            )
            row = client_res.first()
            if row:
                cl, mer = row
                from app.services.email_service import send_otp_requested_email
                from app.api.v1.workers.background_tasks import fire_and_forget
                fire_and_forget(
                    lambda cl=cl, mer=mer: send_otp_requested_email(
                        to_email=mer.email,
                        merchant_name=mer.name,
                        store_name=cl.name,
                        client_id=client_id,
                        whatsapp_number=cl.whatsapp_number or "",
                        store_dashboard_url=f"{cfg['app_url']}/dashboard",
                    ),
                    name="send_otp_requested_email",
                )
        except Exception as e:
            logger.warning("OTP-requested email failed (non-fatal): %s", e)

    return {"ok": True, "method": method}


# ── STEP 3: Verify OTP ────────────────────────────────────────────────────────

@router.post("/verify-otp")
async def verify_otp(request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin(request)
    body            = await request.json()
    phone_number_id = str(body.get("phone_number_id", "")).strip()
    client_id       = str(body.get("client_id", "")).strip()
    cfg             = _cfg()
    client_ip       = get_client_ip(request)
    logger.info("AUDIT verify_otp — ip=%s phone_number_id=%s client_id=%s", client_ip, phone_number_id, client_id)

    if not phone_number_id:
        raise HTTPException(status_code=400, detail="phone_number_id required")

    code = str(body.get("code", "")).strip()
    if not code and client_id:
        from app.models.client_model import Client
        res = await db.execute(select(Client).where(Client.id == client_id))
        cl  = res.scalar_one_or_none()
        if cl and getattr(cl, "pending_otp_code", None):
            code = cl.pending_otp_code

    if not code:
        raise HTTPException(status_code=400, detail="No OTP code available — the merchant has not submitted one yet.")

    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            f"{GRAPH_URL}/{phone_number_id}/verify_code",
            headers={"Authorization": f"Bearer {cfg['system_token']}"},
            json={"code": code},
        )
    data = res.json()
    logger.info("Verify OTP response: %s", data)

    if res.status_code != 200 or not data.get("success"):
        if client_id:
            await _set_client_status(db, client_id, STATUS_OTP_FAILED)
            await _clear_pending_otp(db, client_id)
        raise HTTPException(status_code=400, detail=_merchant_message_for_meta_error(data))

    if client_id:
        await _clear_pending_otp(db, client_id)
        await _set_client_status(db, client_id, STATUS_OTP_SUBMITTED)
    return {"ok": True}


# ── STEP 4: Activate ──────────────────────────────────────────────────────────

@router.post("/activate")
async def activate(request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin(request)
    body            = await request.json()
    phone_number_id = str(body.get("phone_number_id", "")).strip()
    cfg             = _cfg()
    client_ip       = get_client_ip(request)
    logger.info("AUDIT activate — ip=%s phone_number_id=%s", client_ip, phone_number_id)

    if not phone_number_id:
        raise HTTPException(status_code=400, detail="phone_number_id required")

    registration_pin = secrets.token_hex(3)

    async with httpx.AsyncClient(timeout=30) as client:
        reg_res = await client.post(
            f"{GRAPH_URL}/{phone_number_id}/register",
            headers={"Authorization": f"Bearer {cfg['system_token']}"},
            json={"messaging_product": "whatsapp", "pin": registration_pin},
        )
        reg_data = reg_res.json()
        logger.info("Register response: %s", reg_data)
        if reg_res.status_code != 200 or not reg_data.get("success"):
            raise HTTPException(status_code=400, detail=_merchant_message_for_meta_error(reg_data))

        sub_res = await client.post(
            f"{GRAPH_URL}/{phone_number_id}/subscribed_apps",
            headers={"Authorization": f"Bearer {cfg['system_token']}"},
        )
        sub_data = sub_res.json()
        logger.info("Subscribe webhook response: %s", sub_data)
        if sub_res.status_code != 200 or not sub_data.get("success"):
            _, sub_msg = _parse_meta_error(sub_data)
            logger.warning("Webhook subscription warning (non-fatal): %s", sub_msg)

    return {"ok": True, "registration_pin": registration_pin}


# ── STEP 5: Save to DB ────────────────────────────────────────────────────────

@router.post("/save")
async def save_to_db(request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin(request)
    body            = await request.json()
    client_id       = str(body.get("client_id", "")).strip()
    phone_number_id = str(body.get("phone_number_id", "")).strip()
    whatsapp_number = _normalise_number(str(body.get("whatsapp_number", "")))
    client_ip       = get_client_ip(request)
    logger.info("AUDIT save_to_db — ip=%s client_id=%s phone_number_id=%s", client_ip, client_id, phone_number_id)

    if not client_id or not phone_number_id:
        raise HTTPException(status_code=400, detail="client_id and phone_number_id required")

    from app.models.client_model import Client
    from app.models.client_whatsapp_credential import ClientWhatsAppCredential

    client_res = await db.execute(select(Client).where(Client.id == client_id))
    cl = client_res.scalar_one_or_none()
    if not cl:
        raise HTTPException(status_code=404, detail="Store not found")

    dup = await db.execute(
        select(ClientWhatsAppCredential).where(
            ClientWhatsAppCredential.phone_number_id == phone_number_id
        )
    )
    existing = dup.scalar_one_or_none()
    if existing:
        if existing.client_id == client_id:
            existing.whatsapp_number = whatsapp_number
            existing.active          = True
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Phone Number ID already assigned to store {existing.client_id}",
            )
    else:
        db.add(ClientWhatsAppCredential(
            client_id=client_id,
            phone_number_id=phone_number_id,
            whatsapp_number=whatsapp_number,
            active=True,
        ))

    cl.whatsapp_number   = whatsapp_number
    cl.onboarding_status = STATUS_ACTIVE
    await db.commit()
    logger.info("Credential saved — client=%s phone_number_id=%s", client_id, phone_number_id)

    from app.models.merchant import Merchant
    merchant_res = await db.execute(select(Merchant).where(Merchant.id == cl.merchant_id))
    merchant = merchant_res.scalar_one_or_none()
    if merchant:
        merchant.waba_active = True
        await db.commit()

    try:
        if merchant:
            from app.services.email_service import send_store_live_email
            from app.api.v1.workers.background_tasks import fire_and_forget
            fire_and_forget(
                lambda merchant=merchant: send_store_live_email(
                    to_email=merchant.email,
                    merchant_name=merchant.name,
                    store_name=cl.name,
                    client_id=client_id,
                    whatsapp_number=whatsapp_number,
                    store_dashboard_url=f"{_cfg()['app_url']}/dashboard",
                ),
                name="send_store_live_email",
            )
    except Exception as e:
        logger.warning("store-live email failed (non-fatal): %s", e)

    try:
        from app.infrastructure.alerting.slack import alert
        from app.api.v1.workers.background_tasks import fire_and_forget
        fire_and_forget(
            alert(
                title="Store Live on WhatsApp ✅",
                detail=f"*{cl.name}* is now connected and live.",
                level="info",
                fields={
                    "Store ID":        client_id,
                    "Merchant":        merchant.name if merchant else "—",
                    "Phone Number":    "+" + whatsapp_number if whatsapp_number else "—",
                    "Phone Number ID": phone_number_id,
                },
            )
        )
    except Exception:
        pass

    return {"ok": True, "client_id": client_id, "phone_number_id": phone_number_id}


# =============================================================================
# MERCHANT-FACING SELF-SERVE ENDPOINTS
# =============================================================================

merchant_router = APIRouter(
    prefix="/api/v1/merchants",
    tags=["Merchant — WhatsApp Onboarding"],
)

_MAX_NUMBER_ATTEMPTS = 3


@merchant_router.post("/submit-number")
async def merchant_submit_number(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Merchant submits their WhatsApp number from the setup page.
    Runs local validation, stores number, sets status → number_submitted,
    fires Slack alert to admin. Rate-limited to _MAX_NUMBER_ATTEMPTS.
    """
    merchant_id = getattr(request.state, "merchant_id", None)
    if not merchant_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    body   = await request.json()
    digits = _normalise_number(str(body.get("whatsapp_number", "")))

    local_err = _validate_number_local(digits)
    if local_err:
        raise HTTPException(status_code=400, detail=local_err)

    from app.models.client_model import Client
    from app.models.merchant import Merchant

    res = await db.execute(select(Client).where(Client.merchant_id == merchant_id))
    cl  = res.scalars().first()
    if not cl:
        raise HTTPException(status_code=404, detail="Store not found")

    current_status = getattr(cl, "onboarding_status", STATUS_PENDING)
    if current_status in _LOCKED_STATUSES:
        raise HTTPException(
            status_code=403,
            detail="Your number is locked and can no longer be changed. Contact support if you need to update it.",
        )

    attempt_count = getattr(cl, "number_submission_attempts", 0) or 0
    if attempt_count >= _MAX_NUMBER_ATTEMPTS:
        raise HTTPException(
            status_code=429,
            detail=f"You've updated your number {_MAX_NUMBER_ATTEMPTS} times. Please contact support to continue.",
        )

    cl.whatsapp_number            = digits
    cl.onboarding_status          = STATUS_NUMBER_SUBMITTED
    cl.number_submission_attempts = attempt_count + 1
    await db.commit()

    logger.info(
        "Merchant submitted number — merchant_id=%s client=%s number=%s attempt=%d",
        merchant_id, cl.id, digits, attempt_count + 1,
    )

    try:
        from app.infrastructure.alerting.slack import alert
        from app.api.v1.workers.background_tasks import fire_and_forget
        mer_res  = await db.execute(select(Merchant).where(Merchant.id == merchant_id))
        merchant = mer_res.scalar_one_or_none()
        fire_and_forget(
            alert(
                title="New Number Submitted — Action Required 📲",
                detail=f"*{cl.name}* has submitted their WhatsApp number and is ready for WABA onboarding.",
                level="warning",
                fields={
                    "Store ID":   cl.id,
                    "Store Name": cl.name,
                    "Merchant":   merchant.name if merchant else "—",
                    "Email":      merchant.email if merchant else "—",
                    "Number":     "+" + digits,
                    "Attempt":    f"{attempt_count + 1} of {_MAX_NUMBER_ATTEMPTS}",
                    "Next Step":  "Admin panel → Add to WABA",
                },
            )
        )
    except Exception as e:
        logger.warning("Slack alert for number submission failed (non-fatal): %s", e)

    return {
        "ok":              True,
        "whatsapp_number": digits,
        "message": (
            "Your number has been received. "
            "We'll activate your store within 24 hours and notify you by email. "
            "In the meantime, go ahead and set up your catalogue."
        ),
    }


@merchant_router.patch("/whatsapp-number")
async def update_whatsapp_number(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    merchant_id = getattr(request.state, "merchant_id", None)
    if not merchant_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    body   = await request.json()
    digits = _normalise_number(str(body.get("whatsapp_number", "")))

    local_err = _validate_number_local(digits)
    if local_err:
        raise HTTPException(status_code=400, detail=local_err)

    from app.models.client_model import Client

    res = await db.execute(select(Client).where(Client.merchant_id == merchant_id))
    cl  = res.scalars().first()
    if not cl:
        raise HTTPException(status_code=404, detail="Store not found")

    current_status = getattr(cl, "onboarding_status", STATUS_PENDING)
    if current_status in _LOCKED_STATUSES:
        raise HTTPException(
            status_code=403,
            detail="Your number is locked. Contact support to make changes.",
        )

    attempt_count = getattr(cl, "number_submission_attempts", 0) or 0
    if attempt_count >= _MAX_NUMBER_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Too many number updates. Contact support.")

    cl.whatsapp_number            = digits
    cl.onboarding_status          = STATUS_NUMBER_SUBMITTED
    cl.number_submission_attempts = attempt_count + 1
    await db.commit()

    try:
        from app.infrastructure.alerting.slack import alert
        from app.api.v1.workers.background_tasks import fire_and_forget
        fire_and_forget(
            alert(
                title="Number Updated — Re-check Required 🔄",
                detail=f"*{cl.name}* has updated their WhatsApp number.",
                level="warning",
                fields={
                    "Store ID":   cl.id,
                    "New Number": "+" + digits,
                    "Attempt":    f"{attempt_count + 1} of {_MAX_NUMBER_ATTEMPTS}",
                },
            )
        )
    except Exception:
        pass

    return {"ok": True, "whatsapp_number": digits}


@merchant_router.get("/onboarding-status")
async def get_onboarding_status(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    merchant_id = getattr(request.state, "merchant_id", None)
    if not merchant_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    from app.models.client_model import Client

    res = await db.execute(select(Client).where(Client.merchant_id == merchant_id))
    cl  = res.scalars().first()
    if not cl:
        raise HTTPException(status_code=404, detail="Store not found")

    current_status = getattr(cl, "onboarding_status", STATUS_PENDING)
    attempt_count  = getattr(cl, "number_submission_attempts", 0) or 0

    return {
        "onboarding_status": current_status,
        "whatsapp_number":   cl.whatsapp_number or "",
        "number_locked":     current_status in _LOCKED_STATUSES,
        "is_active":         current_status == STATUS_ACTIVE,
        "attempts_left":     max(0, _MAX_NUMBER_ATTEMPTS - attempt_count),
    }


@merchant_router.post("/request-otp")
async def merchant_request_otp(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    merchant_id = getattr(request.state, "merchant_id", None)
    if not merchant_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    from app.core.redis_client import check_rate_limit
    if not await check_rate_limit(f"otp-request:{merchant_id}", max_requests=5, window_seconds=600):
        raise HTTPException(
            status_code=429,
            detail="Too many verification code requests. Please wait a few minutes and try again.",
        )

    body   = await request.json()
    method = str(body.get("method", "SMS")).strip().upper()
    if method not in ("SMS", "VOICE"):
        method = "SMS"

    from app.models.client_model import Client
    from app.models.client_whatsapp_credential import ClientWhatsAppCredential

    res = await db.execute(select(Client).where(Client.merchant_id == merchant_id))
    cl  = res.scalars().first()
    if not cl:
        raise HTTPException(status_code=404, detail="Store not found")

    current_status = getattr(cl, "onboarding_status", STATUS_PENDING)
    allowed = {STATUS_ADDED_TO_WABA, STATUS_OTP_FAILED, STATUS_NUMBER_PERSONAL}

    if current_status not in allowed:
        if current_status in (STATUS_PENDING, STATUS_NUMBER_SUBMITTED):
            raise HTTPException(
                status_code=403,
                detail="Your number hasn't been added to our system yet. You'll receive an email when you can proceed.",
            )
        if current_status == STATUS_OTP_REQUESTED:
            raise HTTPException(status_code=403, detail="A code has already been sent to your phone. Enter it below.")
        if current_status == STATUS_ACTIVE:
            raise HTTPException(status_code=403, detail="Your store is already live.")
        raise HTTPException(status_code=403, detail="Unable to request a code at this stage. Contact support.")

    cred_res = await db.execute(
        select(ClientWhatsAppCredential).where(
            ClientWhatsAppCredential.client_id == cl.id,
            ClientWhatsAppCredential.active == True,  # noqa: E712
        )
    )
    cred = cred_res.scalars().first()
    if not cred or not cred.phone_number_id:
        raise HTTPException(
            status_code=400,
            detail="Your number hasn't been fully added yet. You'll be notified when you can proceed.",
        )

    cfg = _cfg()
    async with httpx.AsyncClient(timeout=30) as client:
        meta_res = await client.post(
            f"{GRAPH_URL}/{cred.phone_number_id}/request_code",
            headers={"Authorization": f"Bearer {cfg['system_token']}"},
            json={"code_method": method, "language": "en_US"},
        )
    data = meta_res.json()
    logger.info("Merchant request_otp — client=%s response=%s", cl.id, data)

    if meta_res.status_code != 200 or not data.get("success"):
        meta_code, _ = _parse_meta_error(data)
        mapped_status = _META_ERROR_STATUS.get(meta_code)
        if mapped_status:
            cl.onboarding_status = mapped_status
            await db.commit()
        raise HTTPException(status_code=400, detail=_merchant_message_for_meta_error(data))

    cl.onboarding_status = STATUS_OTP_REQUESTED
    await db.commit()
    return {"ok": True, "method": method}


@merchant_router.post("/submit-otp")
async def merchant_submit_otp(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    merchant_id = getattr(request.state, "merchant_id", None)
    if not merchant_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    body = await request.json()
    code = str(body.get("code", "")).strip()

    if not code or not code.isdigit() or len(code) != 6:
        raise HTTPException(status_code=400, detail="Enter the 6-digit code from your phone.")

    from app.models.client_model import Client

    res = await db.execute(select(Client).where(Client.merchant_id == merchant_id))
    cl  = res.scalars().first()
    if not cl:
        raise HTTPException(status_code=404, detail="Store not found")

    if getattr(cl, "onboarding_status", None) != STATUS_OTP_REQUESTED:
        raise HTTPException(
            status_code=403,
            detail="No code was requested or your store is already active.",
        )

    cl.pending_otp_code  = code
    cl.onboarding_status = STATUS_OTP_SUBMITTED
    await db.commit()
    logger.info("Merchant submitted OTP — client=%s", cl.id)

    try:
        from app.infrastructure.alerting.slack import alert
        from app.api.v1.workers.background_tasks import fire_and_forget
        fire_and_forget(
            alert(
                title="OTP Submitted — Action Required 🔑",
                detail=f"*{cl.name}* has submitted their WhatsApp verification code. Ready to verify + activate.",
                level="warning",
                fields={
                    "Store ID":   cl.id,
                    "Store Name": cl.name,
                    "Next Step":  "Admin panel → verify OTP → activate → save",
                },
            )
        )
    except Exception:
        pass

    return {
        "ok":     True,
        "message": (
            "Code received. We'll complete your setup shortly and "
            "notify you by email once your store is live."
        ),
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _set_client_status(db: AsyncSession, client_id: str, status: str) -> None:
    from app.models.client_model import Client
    res = await db.execute(select(Client).where(Client.id == client_id))
    cl  = res.scalar_one_or_none()
    if cl:
        cl.onboarding_status = status
        await db.commit()


async def _clear_pending_otp(db: AsyncSession, client_id: str) -> None:
    from app.models.client_model import Client
    res = await db.execute(select(Client).where(Client.id == client_id))
    cl  = res.scalar_one_or_none()
    if cl:
        cl.pending_otp_code = None
        await db.commit()


# ─────────────────────────────────────────────────────────────────────────────
# SHARED: create a Merchant + Client account
# Used by both /approve-merchant (manual entry) and
# /applications/{id}/approve (from a stored application). Keeping this in one
# place means both paths create accounts, send the welcome email, and post
# the Slack alert identically.
# ─────────────────────────────────────────────────────────────────────────────

async def _create_merchant_account(
    *,
    db: AsyncSession,
    name: str,
    email: str,
    whatsapp_number: "str | None",
    initial_password: "str | None" = None,  # kept for API compat; ignored — link flow used instead
) -> dict:
    import secrets
    from datetime import datetime, timezone, timedelta

    # Create the account with a random unusable placeholder password.
    # The merchant will set their real password by clicking the link in the welcome email.
    placeholder_password = secrets.token_urlsafe(32)

    from app.services.merchant_service import MerchantService
    from app.schemas.merchant import MerchantCreate

    create_payload = MerchantCreate(
        name=name,
        email=email,
        password=placeholder_password,
        whatsapp_number=whatsapp_number,
    )

    service  = MerchantService(db)
    merchant = await service.create(create_payload)

    if not merchant:
        return {"ok": False, "detail": "A merchant account with this email already exists."}

    # Generate a set-password token valid for 72 hours.
    # Stored in the existing email_verification_token column — no migration needed.
    set_password_token = secrets.token_urlsafe(32)

    merchant.email_verified                 = True   # admin has already vetted them
    merchant.must_change_password           = True   # login blocked until password is set
    merchant.email_verification_token       = set_password_token
    merchant.email_verification_token_expiry = datetime.now(timezone.utc) + timedelta(hours=72)
    await db.commit()
    await db.refresh(merchant)

    merchant_id = merchant.id
    client_id   = getattr(merchant, "_auto_client_id", None)

    # Build the set-password URL and send the welcome email (one email, no password in it)
    try:
        from app.services.email_service import send_approved_merchant_welcome_email
        from app.api.v1.workers.background_tasks import fire_and_forget
        from app.core.config import get_settings
        _app_url = get_settings().app_url.rstrip("/")
        set_password_url = f"{_app_url}/dashboard?set_password={set_password_token}"

        fire_and_forget(
            lambda: send_approved_merchant_welcome_email(
                to_email=merchant.email,
                merchant_name=merchant.name,
                merchant_id=merchant_id,
                set_password_url=set_password_url,
            ),
            name="send_approved_merchant_welcome_email",
        )
    except Exception as e:
        logger.warning("Failed to send approval email: %s", e)

    # Slack alert
    try:
        from app.infrastructure.alerting.slack import alert
        from app.api.v1.workers.background_tasks import fire_and_forget
        fire_and_forget(alert(
            title="Merchant Approved & Created ✅",
            detail=f"*{merchant.name}* has been approved. Account created and credentials emailed.",
            level="info",
            fields={
                "Merchant ID": merchant_id,
                "Email":       merchant.email,
                "Store ID":    client_id or "—",
            },
        ), name="slack_merchant_approved")
    except Exception:
        pass

    return {
        "ok":          True,
        "merchant_id": merchant_id,
        "client_id":   client_id,
        "email":       merchant.email,
        "response": {
            "ok":          True,
            "merchant_id": merchant_id,
            "client_id":   client_id,
            "email":       merchant.email,
            "message":     f"Account created. Welcome email with login credentials sent to {merchant.email}.",
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# APPROVE MERCHANT  (admin only, manual entry)
# Creates a merchant account by hand-typing the details — used when there's
# no stored application (e.g. someone applied before this table existed, or
# admin is creating an account directly). Protected by ADMIN_SECRET.
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/approve-merchant", tags=["Admin — Merchant Approval"])
async def approve_merchant(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_admin),
):
    """
    Admin-only. Creates a merchant account from hand-typed details.

    Request body (JSON):
        name            str   — merchant/business name
        email           str   — merchant email
        whatsapp_number str   — optional, digits only or with leading +
        initial_password str  — optional; if omitted a secure one is generated

    On success:
        - Creates the Merchant + default Client records in the DB
        - Sends the merchant an email with their login credentials
        - Returns the new merchant's ID and credentials summary
    """
    body = await request.json()

    from app.schemas.merchant import AdminApproveMerchant
    try:
        payload = AdminApproveMerchant(**body)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

    result = await _create_merchant_account(
        db=db,
        name=payload.name,
        email=payload.email,
        whatsapp_number=payload.whatsapp_number,
        initial_password=payload.initial_password,
    )
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["detail"])
    return result["response"]


# ─────────────────────────────────────────────────────────────────────────────
# APPLICATIONS  (admin only)
# The "Apply to Use" form (POST /merchants/apply) writes a row here with
# status="pending". These endpoints let admin see that queue on the
# WhatsApp-setup dashboard and act on it without leaving the page.
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/applications", tags=["Admin — Merchant Approval"])
async def list_applications(request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin(request)
    from app.models.merchant_application import MerchantApplication

    result = await db.execute(
        select(MerchantApplication).order_by(MerchantApplication.created_at.desc())
    )
    apps = result.scalars().all()
    return {
        "applications": [
            {
                "id":                    a.id,
                "business_name":         a.business_name,
                "business_type":         a.business_type,
                "city_state":            a.city_state,
                "full_name":             a.full_name,
                "email":                 a.email,
                "phone_number":          a.phone_number,
                "whatsapp_number":       a.whatsapp_number,
                "num_branches":          a.num_branches,
                "monthly_order_volume":  a.monthly_order_volume,
                "uses_whatsapp_manual":  a.uses_whatsapp_manual,
                "uses_delivery_service": a.uses_delivery_service,
                "heard_about_us":        a.heard_about_us,
                "comments":              a.comments,
                "status":                a.status,
                "last_error":            a.last_error,
                "merchant_id":           a.merchant_id,
                "created_at":            a.created_at.isoformat() if a.created_at else None,
                "registration_status":   a.registration_status,
                "verification_method":   a.verification_method,
                "verification_status":   a.verification_status,
                "transaction_limit":     float(a.transaction_limit) if a.transaction_limit is not None else None,
            }
            for a in apps
        ]
    }


@router.post("/applications/{application_id}/approve", tags=["Admin — Merchant Approval"])
async def approve_application(
    application_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_admin),
):
    """
    Admin-only. Turns a pending (or needs_attention) application into a real
    Merchant + Client account (same effect as /approve-merchant) and marks
    the application "approved" so it drops out of the queue.

    If account creation fails (e.g. the email already belongs to a
    merchant), the application is flagged "needs_attention" instead of
    silently staying "pending" — so it's visibly distinct from an
    untouched application, and can be retried after a fix.

    Request body (JSON, all optional — defaults come from the application):
        name             str — override the account/business name
        email            str — override the email
        whatsapp_number  str — override the WhatsApp number
        initial_password str — if omitted, a secure one is generated
    """
    from datetime import datetime, timezone
    from app.models.merchant_application import MerchantApplication

    res = await db.execute(
        select(MerchantApplication).where(MerchantApplication.id == application_id)
    )
    application = res.scalar_one_or_none()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    if application.status not in ("pending", "needs_attention"):
        raise HTTPException(status_code=400, detail=f"Application already {application.status}")

    try:
        body = await request.json()
    except Exception:
        body = {}
    body = body or {}

    result = await _create_merchant_account(
        db=db,
        name=body.get("name") or application.business_name,
        email=body.get("email") or application.email,
        whatsapp_number=body.get("whatsapp_number") or application.whatsapp_number,
        initial_password=body.get("initial_password"),
    )
    if not result["ok"]:
        application.status      = "needs_attention"
        application.last_error  = result["detail"]
        application.reviewed_at = datetime.now(timezone.utc)
        await db.commit()
        raise HTTPException(status_code=400, detail=result["detail"])

    application.status      = "approved"
    application.merchant_id = result["merchant_id"]
    application.reviewed_at = datetime.now(timezone.utc)
    await db.commit()

    return result["response"]


@router.post("/applications/{application_id}/reject", tags=["Admin — Merchant Approval"])
async def reject_application(
    application_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_admin),
):
    """Admin-only. Dismisses a pending (or needs_attention) application without
    creating an account, and sends the applicant a brief decline email."""
    from datetime import datetime, timezone
    from app.models.merchant_application import MerchantApplication

    res = await db.execute(
        select(MerchantApplication).where(MerchantApplication.id == application_id)
    )
    application = res.scalar_one_or_none()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    if application.status not in ("pending", "needs_attention"):
        raise HTTPException(status_code=400, detail=f"Application already {application.status}")

    application.status      = "rejected"
    application.reviewed_at = datetime.now(timezone.utc)
    await db.commit()

    try:
        from app.services.email_service import send_application_declined_email
        from app.api.v1.workers.background_tasks import fire_and_forget
        fire_and_forget(
            lambda: send_application_declined_email(
                to_email=application.email,
                applicant_name=application.full_name,
                business_name=application.business_name,
            ),
            name="send_application_declined_email",
        )
    except Exception as e:
        logger.warning("Decline email failed (non-fatal): %s", e)

    return {"ok": True, "id": application_id, "status": "rejected"}
