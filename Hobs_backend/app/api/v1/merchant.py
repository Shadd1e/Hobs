import logging
logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select

from app.schemas.merchant import (
    MerchantCreate, MerchantRead, MerchantUpdate, MerchantLogin, MerchantApply,
    ApplyStepOne, ApplyStepTwo, ApplyStepThree, ApplyStepFour,
)
from app.services.merchant_service import MerchantService
from app.db.deps import get_db
from app.core.helpers import get_client_ip

router = APIRouter(prefix="/merchants", tags=["Merchants"])


async def _generate_application_id(db: AsyncSession) -> str:
    """Generate a random Application ID e.g. APA3F7K2 (mirrors the MX/ST scheme
    used for merchants/stores in MerchantService)."""
    import secrets
    import string
    from app.models.merchant_application import MerchantApplication

    alphabet = string.ascii_uppercase + string.digits
    for _ in range(20):
        candidate = "AP" + "".join(secrets.choice(alphabet) for _ in range(6))
        exists = await db.execute(
            select(MerchantApplication.id).where(MerchantApplication.id == candidate)
        )
        if not exists.scalar_one_or_none():
            return candidate
    raise RuntimeError("Failed to generate unique application ID after 20 attempts")


def _generate_link_token() -> str:
    """
    Generate the public, unguessable token used by the "add my WhatsApp
    number" page link. Deliberately separate from the short application ID
    (which shows up in Slack/admin UI) — this token is a bearer credential
    for an unauthenticated public page, so it needs real entropy. 24 random
    bytes (192 bits) makes brute-forcing it computationally meaningless, so
    no DB-uniqueness retry loop is needed the way it is for the short ID.
    """
    import secrets
    return secrets.token_urlsafe(24)


_OPEN_APPLICATION_STATUSES = ("pending", "needs_attention")


def _require_merchant(request: Request) -> str:
    merchant_id = getattr(request.state, "merchant_id", None)
    if not merchant_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    return merchant_id


# ─────────────────────────────────────────────────────────────────────────────
# REGISTER  (DISABLED — public self-registration is no longer available)
# Merchants must apply via POST /merchants/apply and be approved by an admin.
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/", status_code=410)
async def create_merchant_disabled():
    raise HTTPException(
        status_code=410,
        detail=(
            "Self-registration is no longer available. "
            "Please apply at shopprhq.com — our team will review and create your account."
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
# APPLY  (public)
# Accepts the "Apply to Use" form, saves it so admin can review it on the
# WhatsApp-setup dashboard, and sends ONE email to the applicant. No
# Merchant/Client account is created yet — that happens when admin approves
# the application.
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/apply", status_code=200)
async def apply_to_use(
    payload: MerchantApply,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Public endpoint: submit a merchant application.

    Saves the application (status="pending") so it shows up in the admin
    WhatsApp-setup dashboard's "Pending Applications" list, sends the
    applicant one confirmation email, and posts a Slack alert to the team.
    Returns a success message.

    Guards: honeypot field (silent no-op for bots), IP rate limit (3/hr),
    and a dedupe check against existing pending applications.
    """
    # Honeypot — a real applicant never fills this. Pretend success so a bot
    # doesn't learn it was detected, but skip everything else entirely.
    if payload.website:
        logger.warning(
            "Honeypot triggered on /merchants/apply from %s",
            get_client_ip(request),
        )
        return {"message": "Application received. We'll be in touch within 1–2 business days."}

    from app.core.redis_client import check_apply_rate_limit
    client_ip = get_client_ip(request)
    if not await check_apply_rate_limit(client_ip):
        raise HTTPException(
            status_code=429,
            detail="Too many submissions from this connection. Please try again in an hour.",
        )

    try:
        from app.models.merchant_application import MerchantApplication
        from sqlalchemy import or_

        # Dedupe — don't create a second row for someone who already has a
        # pending application (matches on email, and on WhatsApp number if given).
        dedupe_conditions = [MerchantApplication.email == payload.email]
        if payload.whatsapp_number:
            dedupe_conditions.append(MerchantApplication.whatsapp_number == payload.whatsapp_number)

        existing = await db.execute(
            select(MerchantApplication).where(
                MerchantApplication.status == "pending",
                or_(*dedupe_conditions),
            )
        )
        if existing.scalar_one_or_none():
            return {"message": "We already have a pending application from you — we'll be in touch within 1–2 business days."}

        application_id = await _generate_application_id(db)
        link_token     = _generate_link_token()
        application = MerchantApplication(
            id=application_id,
            link_token=link_token,
            business_name=payload.business_name,
            business_type=payload.business_type,
            city_state=payload.city_state,
            full_name=payload.full_name,
            email=payload.email,
            phone_number=payload.phone_number,
            whatsapp_number=payload.whatsapp_number,
            num_branches=payload.num_branches,
            monthly_order_volume=payload.monthly_order_volume,
            uses_whatsapp_manual=payload.uses_whatsapp_manual,
            uses_delivery_service=payload.uses_delivery_service,
            heard_about_us=payload.heard_about_us,
            comments=payload.comments,
            status="pending",
        )
        db.add(application)
        await db.commit()

        from app.services.email_service import send_application_received_email, send_team_application_alert
        from app.api.v1.workers.background_tasks import fire_and_forget

        fire_and_forget(
            lambda: send_application_received_email(
                to_email=payload.email,
                applicant_name=payload.full_name,
                business_name=payload.business_name,
                whatsapp_number=payload.whatsapp_number,
                link_token=link_token,
            ),
            name="send_application_received_email",
        )

        # Notify the team by email (requires TEAM_EMAIL env var to be set)
        fire_and_forget(
            lambda: send_team_application_alert({
                "full_name":            payload.full_name,
                "business_name":        payload.business_name,
                "email":                payload.email,
                "phone_number":         payload.phone_number,
                "whatsapp_number":      payload.whatsapp_number,
                "city_state":           payload.city_state,
                "business_type":        payload.business_type,
                "monthly_order_volume": payload.monthly_order_volume,
                "heard_about_us":       payload.heard_about_us,
                "comments":             payload.comments,
                "application_id":       application_id,
            }),
            name="send_team_application_alert",
        )

        # Team-facing notice — Slack + the admin dashboard's Pending
        # Applications panel cover this now, so there's no separate team email.
        try:
            from app.infrastructure.alerting.slack import alert
            fire_and_forget(alert(
                title="New Merchant Application",
                detail=(
                    f"*{payload.business_name}* ({payload.full_name}) just applied. "
                    f"Review it on the admin WhatsApp-setup page."
                ),
                level="info",
                fields={
                    "Application ID": application_id,
                    "Email":    payload.email,
                    "Phone":    payload.phone_number,
                    "WhatsApp": payload.whatsapp_number or "— not provided —",
                    "City":     payload.city_state,
                    "Type":     payload.business_type,
                    "Volume":   payload.monthly_order_volume,
                },
            ), name="slack_new_application")
        except Exception:
            pass

        return {
            "message": (
                "Application submitted! We've sent a confirmation to your email. "
                "You'll also get a WhatsApp message from us to confirm your "
                "onboarding and book a setup session."
            )
        }

    except HTTPException:
        raise
    except Exception:
        logger.exception("Merchant application submission failed")
        raise HTTPException(status_code=500, detail="Submission failed. Please try again.")


# ─────────────────────────────────────────────────────────────────────────────
# ADD WHATSAPP NUMBER  (public, token-based)
# Backs the link sent in the apply-confirmation email when no WhatsApp number
# was given at application time. Public template: templates/add_whatsapp_number.html
# (served at GET /apply/whatsapp-number/{token} — see main.py).
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/apply/link/{token}")
async def get_application_by_link(token: str, db: AsyncSession = Depends(get_db)):
    from app.models.merchant_application import MerchantApplication

    res = await db.execute(
        select(MerchantApplication).where(MerchantApplication.link_token == token)
    )
    application = res.scalar_one_or_none()
    if not application:
        raise HTTPException(status_code=404, detail="This link isn't valid.")
    if application.status not in _OPEN_APPLICATION_STATUSES:
        raise HTTPException(status_code=410, detail="This application has already been processed.")

    return {
        "business_name":       application.business_name,
        "full_name":            application.full_name,
        "has_whatsapp_number": bool(application.whatsapp_number),
    }


@router.post("/apply/link/{token}")
async def submit_whatsapp_number_for_application(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    from app.models.merchant_application import MerchantApplication
    from app.schemas.merchant import _normalise_phone

    res = await db.execute(
        select(MerchantApplication).where(MerchantApplication.link_token == token)
    )
    application = res.scalar_one_or_none()
    if not application:
        raise HTTPException(status_code=404, detail="This link isn't valid.")
    if application.status not in _OPEN_APPLICATION_STATUSES:
        raise HTTPException(status_code=410, detail="This application has already been processed.")

    body = await request.json()
    try:
        whatsapp_number = _normalise_phone(str(body.get("whatsapp_number", "")))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if not whatsapp_number:
        raise HTTPException(status_code=422, detail="Enter a valid WhatsApp number.")

    application.whatsapp_number = whatsapp_number
    await db.commit()

    try:
        from app.infrastructure.alerting.slack import alert
        from app.api.v1.workers.background_tasks import fire_and_forget
        fire_and_forget(alert(
            title="Application Updated — WhatsApp Number Added",
            detail=f"*{application.business_name}* added their WhatsApp number. Ready to review.",
            level="info",
            fields={
                "Application ID": application.id,
                "WhatsApp":       f"+{whatsapp_number}",
            },
        ), name="slack_application_number_added")
    except Exception:
        pass

    return {"ok": True, "message": "Thanks! We'll reach out to you on WhatsApp to continue."}


# ─────────────────────────────────────────────────────────────────────────────
# VERIFY EMAIL CODE  (auth required)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/verify-email-code")
async def verify_email_code(request: Request, db: AsyncSession = Depends(get_db)):
    merchant_id = _require_merchant(request)
    body        = await request.json()
    code        = str(body.get("code", "")).strip()

    if not code or len(code) != 6 or not code.isdigit():
        raise HTTPException(status_code=400, detail="Enter the 6-digit code from your email.")

    service = MerchantService(db)
    success, reason = await service.verify_email_code(merchant_id, code)

    if not success:
        raise HTTPException(status_code=400, detail=reason)

    await db.commit()

    # ── Welcome email — fires after successful verification ────────────────
    try:
        merchant = await service.get(merchant_id)
        if merchant:
            from app.services.email_service import send_welcome_email
            from app.api.v1.workers.background_tasks import fire_and_forget
            fire_and_forget(lambda: send_welcome_email(
                to_email=merchant.email,
                merchant_name=merchant.name,
                merchant_id=merchant.id,
            ), name="send_welcome_email")
    except Exception:
        pass

    if reason == "already_verified":
        return {"detail": "already_verified"}
    return {"detail": "ok"}


# ─────────────────────────────────────────────────────────────────────────────
# GET OWN PROFILE  (auth required — own merchant only)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/me")
async def get_me(request: Request, db: AsyncSession = Depends(get_db)):
    merchant_id = _require_merchant(request)
    service     = MerchantService(db)
    merchant    = await service.get(merchant_id)
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")
    return {
        "id":               merchant.id,
        "name":             merchant.name,
        "email":            merchant.email,
        "email_verified":   merchant.email_verified,
        "whatsapp_number":  merchant.whatsapp_number,
    }


# ─────────────────────────────────────────────────────────────────────────────
# RESUME WIZARD  (public — declared before /{merchant_id} catch-all)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/apply/resume/{resume_token}", status_code=200)
async def apply_wizard_resume(resume_token: str, db: AsyncSession = Depends(get_db)):
    """
    Used by the frontend (lib/api.ts applyResume) both for the "continue your
    application" reminder-email link AND every time get-started/page.tsx
    mounts mid-wizard, to repopulate already-entered fields. Must return the
    full ResumeState shape, not just {application_id, current_step} — the
    earlier version only returned those two fields, which would silently
    blank out every field the applicant had already filled in on resume.

    has_cac_number / has_bvn / has_nin are booleans rather than echoing the
    raw values back — those are sensitive once submitted, the UI only needs
    to know whether to show "on file" vs. an empty input.

    Public — no additional auth beyond the resume_token itself (256-bit secret).
    """
    from app.models.merchant_application import MerchantApplication

    res = await db.execute(
        select(MerchantApplication).where(MerchantApplication.resume_token == resume_token)
    )
    app = res.scalar_one_or_none()

    if not app:
        raise HTTPException(status_code=404, detail="This link isn't valid.")

    if app.status != _DRAFT_STATUS:
        raise HTTPException(
            status_code=410,
            detail="This application has already been submitted.",
        )

    if app.resume_token_expires_at and app.resume_token_expires_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=410,
            detail="This link has expired. Please start a new application.",
        )

    return {
        "current_step":           app.current_step,
        "full_name":              app.full_name,
        "email":                  app.email,
        "phone_number":           app.phone_number,
        "whatsapp_number":        app.whatsapp_number,
        "business_name":          app.business_name,
        "business_type":          app.business_type,
        "city_state":             app.city_state,
        "registration_status":    app.registration_status,
        "num_branches":           app.num_branches,
        "monthly_order_volume":   app.monthly_order_volume,
        "uses_whatsapp_manual":   app.uses_whatsapp_manual,
        "uses_delivery_service":  app.uses_delivery_service,
        "heard_about_us":         app.heard_about_us,
        "comments":               app.comments,
        "verification_method":    app.verification_method if app.verification_method in ("bvn", "nin") else None,
        "verification_status":    app.verification_status,
        "has_cac_number":         bool(app.cac_number),
        "has_bvn":                bool(app.bvn),
        "has_nin":                bool(app.nin),
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET BY ID  (auth required — own merchant only)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{merchant_id}", response_model=MerchantRead)
async def get_merchant(merchant_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    authed = _require_merchant(request)
    if merchant_id != authed:
        raise HTTPException(status_code=403, detail="Access denied")
    service  = MerchantService(db)
    merchant = await service.get(merchant_id)
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")
    return merchant


# ─────────────────────────────────────────────────────────────────────────────
# UPDATE  (auth required — own merchant only)
# ─────────────────────────────────────────────────────────────────────────────

@router.put("/{merchant_id}", response_model=MerchantRead)
async def update_merchant(
    merchant_id: str, payload: MerchantUpdate, request: Request, db: AsyncSession = Depends(get_db)
):
    authed = _require_merchant(request)
    if merchant_id != authed:
        raise HTTPException(status_code=403, detail="Access denied")
    service = MerchantService(db)
    try:
        merchant = await service.update(merchant_id, payload.model_dump(exclude_unset=True))
        if not merchant:
            raise HTTPException(status_code=404, detail="Merchant not found")
        return merchant
    except IntegrityError:
        raise HTTPException(status_code=400, detail="Failed to update merchant")


# ─────────────────────────────────────────────────────────────────────────────
# DELETE  (auth required — own merchant only)
# ─────────────────────────────────────────────────────────────────────────────

@router.delete("/{merchant_id}", response_model=dict)
async def delete_merchant(merchant_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    authed = _require_merchant(request)
    if merchant_id != authed:
        raise HTTPException(status_code=403, detail="Access denied")
    service = MerchantService(db)
    success = await service.delete(merchant_id)
    if not success:
        raise HTTPException(status_code=404, detail="Merchant not found")
    return {"detail": "Deleted successfully"}


# ─────────────────────────────────────────────────────────────────────────────
# LOGIN  (public)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/login")
async def login_merchant(payload: MerchantLogin, request: Request, db: AsyncSession = Depends(get_db)):
    from app.core.security import create_access_token
    from app.core.redis_client import check_login_rate_limit

    client_ip = get_client_ip(request)
    if not await check_login_rate_limit(client_ip, payload.email):
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts. Please wait 15 minutes before trying again.",
            headers={"Retry-After": "900"},
        )

    service  = MerchantService(db)
    merchant = await service.authenticate(payload.email, payload.password)
    if not merchant:
        raise HTTPException(status_code=401, detail="Invalid credentials or account locked")
    token          = create_access_token(subject=merchant.id)
    email_verified = getattr(merchant, "email_verified", False) or False
    must_change_pw = getattr(merchant, "must_change_password", False) or False
    return {
        "access_token":        token,
        "token_type":          "bearer",
        "merchant_id":         merchant.id,
        "name":                merchant.name,
        "email":               merchant.email,
        "email_verified":      email_verified,
        "must_change_password": must_change_pw,
    }


# ─────────────────────────────────────────────────────────────────────────────
# FORGOT PASSWORD  (public — step 1: request a reset code)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/forgot-password")
async def forgot_password(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Sends a 6-digit password reset code to the merchant's registered email.
    Always returns 200 regardless of whether the email exists (no enumeration).
    Code is stored in Redis with a 10-minute TTL.
    """
    from app.core.redis_client import check_login_rate_limit

    body  = await request.json()
    email = (body.get("email") or "").strip().lower()

    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="A valid email address is required.")

    client_ip = get_client_ip(request)
    if not await check_login_rate_limit(client_ip, email):
        # Return the same generic message — don't confirm the email exists or reveal the limit
        return {"detail": "If that email is registered, a reset code has been sent."}

    service  = MerchantService(db)
    from sqlalchemy import select as _sel
    from app.models.merchant import Merchant as _M

    # Look up merchant by email — silently succeed even if not found
    res      = await db.execute(_sel(_M).where(_M.email == email))
    merchant = res.scalar_one_or_none()

    if merchant:
        import random
        code = f"{random.randint(100000, 999999)}"

        # Store in Redis: key = pwd_reset:{email}, value = code, TTL = 10 min
        try:
            from app.core.redis_client import redis_service
            r = await redis_service.get_client()
            await r.setex(f"pwd_reset:{email}", 600, code)
        except Exception as e:
            logger.warning("Redis unavailable for pwd reset code: %s", e)
            raise HTTPException(status_code=503, detail="Service temporarily unavailable. Try again shortly.")

        try:
            from app.services.email_service import send_password_reset_email
            from app.api.v1.workers.background_tasks import fire_and_forget
            fire_and_forget(lambda: send_password_reset_email(
                to_email=email,
                merchant_name=merchant.name,
                code=code,
            ), name="send_password_reset_email")
        except Exception as e:
            logger.warning("Password reset email failed (non-fatal): %s", e)

    return {"detail": "If that email is registered, a reset code has been sent."}


# ─────────────────────────────────────────────────────────────────────────────
# RESET PASSWORD  (public — step 2: verify code + set new password)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/reset-password")
async def reset_password(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Verifies the 6-digit code sent to the merchant's email and updates
    their password. Code is consumed on first successful use.
    """
    body         = await request.json()
    email        = (body.get("email") or "").strip().lower()
    code         = str(body.get("code") or "").strip()
    new_password = str(body.get("new_password") or "").strip()

    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="A valid email address is required.")
    if not code or len(code) != 6 or not code.isdigit():
        raise HTTPException(status_code=400, detail="Enter the 6-digit code from your email.")
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters.")

    # Verify code from Redis
    try:
        from app.core.redis_client import redis_service
        r        = await redis_service.get_client()
        key      = f"pwd_reset:{email}"
        stored   = await r.get(key)
    except Exception as e:
        logger.warning("Redis unavailable for pwd reset verify: %s", e)
        raise HTTPException(status_code=503, detail="Service temporarily unavailable. Try again shortly.")

    if not stored or stored != code:
        raise HTTPException(status_code=400, detail="Incorrect or expired code. Request a new one.")

    # Find merchant and update password
    from sqlalchemy import select as _sel
    from app.models.merchant import Merchant as _M
    from app.core.security import get_password_hash

    res      = await db.execute(_sel(_M).where(_M.email == email))
    merchant = res.scalar_one_or_none()

    if not merchant:
        raise HTTPException(status_code=400, detail="Incorrect or expired code. Request a new one.")

    merchant.password_hash        = get_password_hash(new_password)
    merchant.failed_attempts      = 0   # clear any lockout
    merchant.must_change_password = False  # first-login gate satisfied
    await db.commit()

    # Consume the code so it cannot be reused
    try:
        await r.delete(key)
    except Exception:
        pass

    return {"detail": "Password updated. You can now sign in with your new password."}


# ─────────────────────────────────────────────────────────────────────────────
# SET PASSWORD  (public — token-driven, used on first login after approval)
#
# Flow: admin approves → welcome email contains ?set_password=<token> link →
#       merchant clicks → dashboard JS POSTs here with token + chosen password →
#       token consumed, password set, must_change_password cleared → merchant logs in.
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/set-password")
async def set_password_via_token(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Validates the set-password token from the approval email and sets the
    merchant's password for the first time.  Token is single-use and expires
    after 72 hours.
    """
    from datetime import datetime, timezone
    from sqlalchemy import select as _sel
    from app.models.merchant import Merchant as _M
    from app.core.security import get_password_hash

    body         = await request.json()
    token        = str(body.get("token") or "").strip()
    new_password = str(body.get("new_password") or "").strip()

    if not token:
        raise HTTPException(status_code=400, detail="Token is required.")
    if len(new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")

    res      = await db.execute(
        _sel(_M).where(_M.email_verification_token == token)
    )
    merchant = res.scalar_one_or_none()

    if not merchant:
        raise HTTPException(status_code=400, detail="This link is invalid or has already been used.")

    expiry = merchant.email_verification_token_expiry
    if expiry and expiry < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=400,
            detail="This link has expired. Contact support to get a new one.",
        )

    merchant.password_hash                   = get_password_hash(new_password)
    merchant.must_change_password            = False
    merchant.failed_attempts                 = 0
    merchant.email_verification_token        = None
    merchant.email_verification_token_expiry = None
    await db.commit()

    return {"detail": "Password set. You can now sign in."}


# ─────────────────────────────────────────────────────────────────────────────
# RESEND VERIFICATION  (auth required)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/resend-verification")
async def resend_verification(request: Request, db: AsyncSession = Depends(get_db)):
    merchant_id = _require_merchant(request)
    service     = MerchantService(db)
    merchant    = await service.get(merchant_id)
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")
    if merchant.email_verified:
        return {"detail": "Email already verified"}

    new_code = await service.refresh_verification_code(merchant_id)
    if not new_code:
        raise HTTPException(status_code=400, detail="Could not generate code")
    await db.commit()
    await db.refresh(merchant)

    try:
        from app.services.email_service import send_verification_email
        from app.api.v1.workers.background_tasks import fire_and_forget
        fire_and_forget(lambda: send_verification_email(
            to_email=merchant.email,
            merchant_name=merchant.name,
            merchant_id=merchant.id,
            token=new_code,
            whatsapp_number=merchant.whatsapp_number,
        ), name="send_resend_verification_email")
    except Exception as e:
        logger.warning("Resend verification email failed: %s", e)

    return {"detail": "Verification code sent"}


# ─────────────────────────────────────────────────────────────────────────────
# CHANGE EMAIL  (auth required — before verification only)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/change-email")
async def change_email(request: Request, db: AsyncSession = Depends(get_db)):
    merchant_id = _require_merchant(request)
    body        = await request.json()
    new_email   = body.get("email", "").strip().lower()

    if not new_email or "@" not in new_email:
        raise HTTPException(status_code=400, detail="Valid email address required")

    service  = MerchantService(db)
    merchant = await service.get(merchant_id)
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")
    if merchant.email_verified:
        raise HTTPException(status_code=400, detail="Email already verified and cannot be changed")

    from sqlalchemy import select as sa_select
    from app.models.merchant import Merchant as MerchantModel
    existing = await db.execute(
        sa_select(MerchantModel).where(
            MerchantModel.email == new_email,
            MerchantModel.id    != merchant_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="That email is already in use")

    merchant.email          = new_email
    merchant.email_verified = False
    new_code = await service.refresh_verification_code(merchant_id)
    await db.commit()
    await db.refresh(merchant)

    try:
        from app.services.email_service import send_verification_email
        from app.api.v1.workers.background_tasks import fire_and_forget
        fire_and_forget(lambda: send_verification_email(
            to_email=merchant.email,
            merchant_name=merchant.name,
            merchant_id=merchant.id,
            token=new_code or merchant.email_verification_token,
            whatsapp_number=merchant.whatsapp_number,
        ), name="send_change_email_verification")
    except Exception as e:
        logger.warning("Change email send failed: %s", e)

    return {"detail": "Email updated and verification sent", "email": new_email}


# ─────────────────────────────────────────────────────────────────────────────
# ONBOARDING WIZARD  (public — 4-step resumable "Apply to Use" flow)
#
# Step 1  POST /merchants/apply/start
#   Accepts name + contact details, creates a "draft" MerchantApplication,
#   returns {application_id, resume_token} so the frontend can continue.
#
# Step 2  PATCH /merchants/apply/resume/{resume_token}/business
#   Business details.
#
# Step 3  PATCH /merchants/apply/resume/{resume_token}/verification
#   Identity / business verification (CAC, BVN, or NIN).
#   Calls verification_service — currently stubs to "pending_manual_review"
#   if no IDENTITY_PROVIDER_API_KEY is set.
#
# Step 4  POST /merchants/apply/resume/{resume_token}/submit
#   Terms & indemnity acceptance. Finalises the application (status →
#   "pending"), sends the applicant their confirmation email, and posts a
#   Slack alert — identical side-effects to the legacy /apply endpoint.
#
# Resume GET /merchants/apply/resume/{resume_token}
#   Returns the full ResumeState (current_step + every field captured so
#   far) so the frontend can both drop the user back at the right wizard
#   screen AND repopulate already-entered fields after following the
#   reminder link or refreshing mid-wizard.
#
# Auth scheme for steps 2-4:
#   The resume_token is a 32-byte URL-safe secret generated at step 1 and
#   stored against the application row. It is NOT a JWT and is NOT the
#   same as link_token (which backs the older add-WhatsApp-number page).
#   It expires 7 days after creation. The frontend (lib/api.ts) sends it as
#   a literal path segment on every step 2-4 call and does NOT send an
#   Authorization header for these — resume_token in the URL is both the
#   lookup key and the credential; see _load_draft. There is deliberately
#   no application_id anywhere in these URLs either — resume_token alone
#   is unique per application and is everything the frontend has on hand.
#
# This is deliberately separate from the merchant JWT auth used elsewhere
# so that unauthenticated applicants (who have no account yet) can still
# resume their draft.
# ─────────────────────────────────────────────────────────────────────────────

import secrets as _secrets
from datetime import datetime, timezone, timedelta

_RESUME_TOKEN_TTL_DAYS = 7
_DRAFT_STATUS = "draft"


def _generate_resume_token() -> str:
    """32 random bytes = 256 bits of entropy; URL-safe base64 encoding."""
    return _secrets.token_urlsafe(32)


def _resume_token_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=_RESUME_TOKEN_TTL_DAYS)


async def _load_draft(
    resume_token: str,
    db: AsyncSession,
):
    """
    Fetch a draft MerchantApplication by its resume_token.

    The frontend wizard (app/get-started/page.tsx via lib/api.ts) carries the
    resume_token in the URL path on every step-2/3/4 call and never sends an
    application_id or an Authorization header for these — resume_token alone
    is the lookup key and the credential. It's generated with
    _generate_resume_token() (see below) and is unique per application, so
    looking it up directly is equivalent to the old "find by id, then check
    token matches" approach but matches what's actually being sent on the
    wire.

    Returns the application row, or raises HTTPException with an appropriate
    status code. Used by steps 2, 3, and 4.
    """
    from app.models.merchant_application import MerchantApplication

    res = await db.execute(
        select(MerchantApplication).where(MerchantApplication.resume_token == resume_token)
    )
    app = res.scalar_one_or_none()

    if not app:
        raise HTTPException(status_code=403, detail="Invalid or missing resume token.")

    # Only draft applications can be continued through the wizard.
    # A "pending" application has already been submitted via step 4.
    if app.status != _DRAFT_STATUS:
        raise HTTPException(
            status_code=410,
            detail="This application has already been submitted and can no longer be edited.",
        )

    if app.resume_token_expires_at and app.resume_token_expires_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=410,
            detail="Your session has expired. Please start a new application.",
        )

    return app


# ── Step 1: contact details ───────────────────────────────────────────────────

@router.post("/apply/start", status_code=200)
async def apply_wizard_step_one(
    payload: ApplyStepOne,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Step 1 of the onboarding wizard.

    Creates a draft MerchantApplication with name + contact details and
    returns the application_id + resume_token the frontend needs to
    continue through steps 2-4.

    Guards: honeypot field, IP rate limit (shared with /apply), and a
    dedupe check on email so clicking "Back" and resubmitting step 1
    doesn't create a second draft.
    """
    # Honeypot — same guard as the legacy /apply endpoint.
    if payload.website:
        logger.warning(
            "Honeypot triggered on /merchants/apply/start from %s",
            get_client_ip(request),
        )
        # Return a plausible-looking success so the bot doesn't learn it was caught.
        return {
            "application_id": "AP000000",
            "resume_token": _generate_resume_token(),
            "current_step": 2,
        }

    from app.core.redis_client import check_apply_rate_limit
    client_ip = get_client_ip(request)
    if not await check_apply_rate_limit(client_ip):
        raise HTTPException(
            status_code=429,
            detail="Too many submissions from this connection. Please try again in an hour.",
        )

    from app.models.merchant_application import MerchantApplication
    from sqlalchemy import or_

    try:
        # Dedupe: if this email already has an open draft, return its token
        # so the applicant can resume rather than creating a second row.
        existing_res = await db.execute(
            select(MerchantApplication).where(
                MerchantApplication.email == payload.email,
                MerchantApplication.status == _DRAFT_STATUS,
            )
        )
        existing = existing_res.scalar_one_or_none()

        if existing:
            # Refresh the resume token so the returned one is always valid.
            existing.resume_token            = _generate_resume_token()
            existing.resume_token_expires_at = _resume_token_expiry()
            existing.last_activity_at        = datetime.now(timezone.utc)
            # Update contact details in case they corrected a typo.
            existing.full_name      = payload.full_name
            existing.phone_number   = payload.phone_number
            existing.whatsapp_number = payload.whatsapp_number
            await db.commit()
            return {
                "application_id": existing.id,
                "resume_token":   existing.resume_token,
                "current_step":   existing.current_step,
            }

        # Also block if there's already a non-draft (pending/approved/etc.)
        # application for this email, to avoid confusing duplicates.
        pending_res = await db.execute(
            select(MerchantApplication).where(
                MerchantApplication.email == payload.email,
                MerchantApplication.status.in_(("pending", "approved", "needs_attention")),
            )
        )
        if pending_res.scalar_one_or_none():
            return {
                "message": (
                    "We already have an application on file for this email address. "
                    "Our team will be in touch within 1–2 business days."
                )
            }

        application_id = await _generate_application_id(db)
        resume_token   = _generate_resume_token()
        link_token     = _generate_link_token()

        application = MerchantApplication(
            id=application_id,
            full_name=payload.full_name,
            email=payload.email,
            phone_number=payload.phone_number,
            whatsapp_number=payload.whatsapp_number,
            link_token=link_token,
            resume_token=resume_token,
            resume_token_expires_at=_resume_token_expiry(),
            status=_DRAFT_STATUS,
            current_step=2,
            last_activity_at=datetime.now(timezone.utc),
        )
        db.add(application)
        await db.commit()

        return {
            "application_id": application_id,
            "resume_token":   resume_token,
            "current_step":   2,
        }

    except HTTPException:
        raise
    except Exception:
        logger.exception("Wizard step 1 failed")
        raise HTTPException(status_code=500, detail="Submission failed. Please try again.")


# ── Step 2: business details ──────────────────────────────────────────────────

@router.patch("/apply/resume/{resume_token}/business", status_code=200)
async def apply_wizard_step_two(
    resume_token: str,
    payload: ApplyStepTwo,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Step 2: business details (name, type, city, registration status, etc.).

    Matches lib/api.ts applyStepTwo: PATCH .../apply/resume/{resume_token}/business,
    no Authorization header — resume_token in the path is both the lookup key
    and the credential (see _load_draft).
    """
    app = await _load_draft(resume_token, db)

    try:
        app.business_name       = payload.business_name
        app.business_type       = payload.business_type
        app.city_state          = payload.city_state
        app.registration_status = payload.registration_status
        app.num_branches        = payload.num_branches
        app.monthly_order_volume = payload.monthly_order_volume
        app.uses_whatsapp_manual  = payload.uses_whatsapp_manual
        app.uses_delivery_service = payload.uses_delivery_service
        app.heard_about_us      = payload.heard_about_us
        app.comments            = payload.comments
        app.current_step        = 3
        app.last_activity_at    = datetime.now(timezone.utc)
        await db.commit()

        return {
            "current_step":        3,
            "registration_status": app.registration_status,
        }

    except HTTPException:
        raise
    except Exception:
        logger.exception("Wizard step 2 failed for resume_token %s", resume_token)
        raise HTTPException(status_code=500, detail="Could not save business details. Please try again.")


# ── Step 3: identity / business verification ──────────────────────────────────

@router.patch("/apply/resume/{resume_token}/verification", status_code=200)
async def apply_wizard_step_three(
    resume_token: str,
    payload: ApplyStepThree,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Step 3: identity / business verification.

    For registered businesses: CAC RC/BN number.
    For unregistered businesses: BVN or NIN (one required, decided by
    verification_method).

    Calls verification_service — currently stubs every check to
    "pending_manual_review" because no provider API key is configured.
    The application still advances so onboarding isn't blocked.

    Matches lib/api.ts applyStepThree: PATCH .../apply/resume/{resume_token}/verification,
    no Authorization header.
    """
    app = await _load_draft(resume_token, db)

    # registration_status must have been set in step 2.
    if not app.registration_status:
        raise HTTPException(
            status_code=422,
            detail="Business details (step 2) must be completed before verification.",
        )

    from app.services.verification_service import (
        verify_cac, verify_bvn, verify_nin, get_transaction_limit,
    )

    try:
        reg = app.registration_status  # "registered" | "unregistered"

        if reg == "registered":
            if not payload.cac_number:
                raise HTTPException(
                    status_code=422,
                    detail="CAC RC/BN number is required for registered businesses.",
                )
            result = await verify_cac(payload.cac_number, app.business_name or "")
            app.cac_number          = payload.cac_number
            app.verification_method = "cac"

        else:  # unregistered
            method = payload.verification_method
            if method == "bvn":
                if not payload.bvn:
                    raise HTTPException(status_code=422, detail="BVN is required.")
                result = await verify_bvn(payload.bvn, app.full_name)
                app.bvn                 = payload.bvn
                app.verification_method = "bvn"
            elif method == "nin":
                if not payload.nin:
                    raise HTTPException(status_code=422, detail="NIN is required.")
                result = await verify_nin(payload.nin, app.full_name)
                app.nin                 = payload.nin
                app.verification_method = "nin"
            else:
                raise HTTPException(
                    status_code=422,
                    detail="verification_method must be 'bvn' or 'nin' for unregistered businesses.",
                )

        app.verification_status        = result.status
        app.verification_name_on_file  = result.name_on_file
        app.transaction_limit          = get_transaction_limit(reg, result.status)
        app.current_step               = 4
        app.last_activity_at           = datetime.now(timezone.utc)
        await db.commit()

        return {
            "current_step":        4,
            "verification_status": result.status,
            "transaction_limit":   app.transaction_limit,
        }

    except HTTPException:
        raise
    except Exception:
        logger.exception("Wizard step 3 failed for resume_token %s", resume_token)
        raise HTTPException(status_code=500, detail="Verification step failed. Please try again.")


# ── Step 4: terms acceptance — finalises the application ─────────────────────

@router.post("/apply/resume/{resume_token}/submit", status_code=200)
async def apply_wizard_step_four(
    resume_token: str,
    payload: ApplyStepFour,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Step 4: terms & indemnity acceptance.  Finalises the application.

    - Records terms_version, acceptance timestamp, and client IP for audit.
    - Flips status from "draft" → "pending" so it appears in the admin queue.
    - Sends the applicant a confirmation email (same as legacy /apply).
    - Posts a Slack alert to the team.

    Matches lib/api.ts applyStepFour: POST .../apply/resume/{resume_token}/submit,
    no Authorization header. Returns {message, application_id} per
    StepFourPayload's response type.
    """
    app = await _load_draft(resume_token, db)
    application_id = app.id

    # Guard: steps 2 and 3 must have been completed.
    if not app.business_name or not app.registration_status:
        raise HTTPException(
            status_code=422,
            detail="Business details (step 2) must be completed before submitting.",
        )
    if not app.verification_method:
        raise HTTPException(
            status_code=422,
            detail="Identity verification (step 3) must be completed before submitting.",
        )

    client_ip = get_client_ip(request)

    try:
        app.terms_version     = payload.terms_version
        app.terms_accepted    = True
        app.terms_accepted_at = datetime.now(timezone.utc)
        app.terms_accepted_ip = client_ip
        app.status            = "pending"
        app.current_step      = 4  # stays at 4 — wizard is complete
        app.last_activity_at  = datetime.now(timezone.utc)
        await db.commit()

        # ── Confirmation email to applicant ───────────────────────────────
        from app.services.email_service import (
            send_application_received_email,
            send_team_application_alert,
        )
        from app.api.v1.workers.background_tasks import fire_and_forget

        fire_and_forget(
            lambda: send_application_received_email(
                to_email=app.email,
                applicant_name=app.full_name,
                business_name=app.business_name or "",
                whatsapp_number=app.whatsapp_number,
                link_token=app.link_token,
            ),
            name="wizard_send_application_received_email",
        )

        # ── Team alert (email) ────────────────────────────────────────────
        fire_and_forget(
            lambda: send_team_application_alert({
                "full_name":            app.full_name,
                "business_name":        app.business_name or "",
                "email":                app.email,
                "phone_number":         app.phone_number,
                "whatsapp_number":      app.whatsapp_number,
                "city_state":           app.city_state or "",
                "business_type":        app.business_type or "",
                "monthly_order_volume": app.monthly_order_volume,
                "heard_about_us":       app.heard_about_us,
                "comments":             app.comments,
                "application_id":       application_id,
            }),
            name="wizard_send_team_application_alert",
        )

        # ── Slack alert ───────────────────────────────────────────────────
        try:
            from app.infrastructure.alerting.slack import alert
            fire_and_forget(alert(
                title="New Merchant Application (Wizard)",
                detail=(
                    f"*{app.business_name}* ({app.full_name}) completed the onboarding wizard. "
                    f"Review it on the admin WhatsApp-setup page."
                ),
                level="info",
                fields={
                    "Application ID":  application_id,
                    "Email":           app.email,
                    "Phone":           app.phone_number,
                    "WhatsApp":        app.whatsapp_number or "— not provided —",
                    "City":            app.city_state or "",
                    "Type":            app.business_type or "",
                    "Registration":    app.registration_status or "",
                    "Verification":    app.verification_status or "pending_manual_review",
                    "Volume":          app.monthly_order_volume or "",
                },
            ), name="wizard_slack_new_application")
        except Exception:
            pass  # Slack alert failure must never block the response.

        return {
            "message": (
                "Application submitted! We've sent a confirmation to your email. "
                "You'll also get a WhatsApp message from us to confirm your "
                "onboarding and book a setup session."
            ),
            "application_id": application_id,
        }

    except HTTPException:
        raise
    except Exception:
        logger.exception("Wizard step 4 failed for resume_token %s", resume_token)
        raise HTTPException(status_code=500, detail="Could not submit application. Please try again.")

