import os
import asyncio
import logging
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.core.logging_config import setup_logging
from app.core.tenant import TenantMiddleware

# --------------------------------------------------
# LOGGING (MUST BE FIRST)
# --------------------------------------------------
setup_logging()
logger = logging.getLogger(__name__)

# --------------------------------------------------
# SENTRY (right after logging, before anything else runs, so startup
# crashes and early import errors get captured too)
# --------------------------------------------------
_SENTRY_DSN = os.getenv("SENTRY_DSN", "")
_ENVIRONMENT = os.getenv("ENVIRONMENT", "production").lower()

if _SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration

    # This codebase logs a LOT of handled failures via logger.error() inside
    # except blocks (webhook edge cases, notification sends, etc.) without
    # re-raising — those currently vanish unless something also happens to
    # fire a Slack alert right next to them. event_level=ERROR turns every
    # logger.error() call into a Sentry event too, not just unhandled
    # exceptions, so those stop being invisible.
    _logging_integration = LoggingIntegration(
        level=logging.INFO,    # breadcrumbs: INFO and above
        event_level=logging.ERROR,  # events: ERROR and above
    )

    def _scrub_sensitive(event, hint):
        """
        Defense in depth on top of send_default_pii=False (the default).
        This app encrypts NIN/BVN/CAC at rest (app/core/crypto.py) and
        handles a single shared ADMIN_SECRET — make sure none of that, or
        common auth headers, ever leaves in an event payload even if it
        ends up in a log message, request body, or local variable capture.
        """
        _SENSITIVE_KEYS = {
            "nin", "bvn", "cac_number", "cac", "password", "admin_secret",
            "authorization", "x-admin-token", "x-cron-secret", "token",
            "access_token", "refresh_token", "secret",
        }

        def _redact(obj):
            if isinstance(obj, dict):
                return {
                    k: ("[Filtered]" if k.lower() in _SENSITIVE_KEYS else _redact(v))
                    for k, v in obj.items()
                }
            if isinstance(obj, list):
                return [_redact(v) for v in obj]
            return obj

        for key in ("request", "extra", "contexts"):
            if key in event:
                event[key] = _redact(event[key])
        return event

    sentry_sdk.init(
        dsn=_SENTRY_DSN,
        environment=_ENVIRONMENT,
        release=os.getenv("RAILWAY_GIT_COMMIT_SHA", None),  # Railway sets this automatically
        integrations=[FastApiIntegration(), StarletteIntegration(), _logging_integration],
        # Error tracking, not perf tracing — keep this at 0 unless you
        # specifically want transaction/latency data too (costs quota).
        traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0")),
        send_default_pii=False,
        before_send=_scrub_sensitive,
    )
    logger.info("Sentry initialized (environment=%s)", _ENVIRONMENT)
elif _ENVIRONMENT != "local":
    logger.warning(
        "SENTRY_DSN not set — unhandled exceptions and logged errors will "
        "only reach Slack (see global_exception_handler) and stdout logs, "
        "not Sentry. Set SENTRY_DSN to enable error monitoring."
    )

# --------------------------------------------------
# Lifespan
# --------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Starting HoBS API")

    _startup_env = os.getenv("ENVIRONMENT", "production").lower()
    if _startup_env != "local":
        _required = {
            "META_APP_SECRET": os.getenv("META_APP_SECRET"),
        }
        _missing = [k for k, v in _required.items() if not v]
        if _missing:
            logger.critical("Missing required environment variables: %s", _missing)
            import sys; sys.exit(1)

        # PAYSTACK_SECRET_KEY / PAYSTACK_WEBHOOK_SECRET are intentionally NOT
        # in _required above -- Paystack payments aren't wired up yet for
        # this deployment, so the app is allowed to boot without them. Each
        # Paystack request path (see app/api/v1/paystack.py) independently
        # checks for PAYSTACK_WEBHOOK_SECRET and rejects if missing, so this
        # doesn't silently disable webhook signature verification -- it just
        # stops the ABSENCE of Paystack config from blocking the whole app
        # (including the unrelated Meta/WhatsApp webhook) from starting.
        # Add PAYSTACK_SECRET_KEY and PAYSTACK_WEBHOOK_SECRET back to
        # _required once Paystack is actually turned on for this deployment.
        _optional_paystack = {
            "PAYSTACK_SECRET_KEY": os.getenv("PAYSTACK_SECRET_KEY"),
            "PAYSTACK_WEBHOOK_SECRET": os.getenv("PAYSTACK_WEBHOOK_SECRET"),
        }
        _missing_paystack = [k for k, v in _optional_paystack.items() if not v]
        if _missing_paystack:
            logger.warning(
                "Paystack env vars not set (%s) -- Paystack payment routes "
                "will reject requests until these are configured.",
                _missing_paystack,
            )

        _admin_secret = os.getenv("ADMIN_SECRET", "")
        if not _admin_secret:
            logger.critical(
                "ADMIN_SECRET is not set. "
                "Set a secure random value (32+ chars) in Railway environment variables."
            )
            import sys; sys.exit(1)
        if len(_admin_secret) < 32:
            logger.critical(
                "ADMIN_SECRET is too short (%d chars). Minimum is 32. "
                "Generate one with: python3 -c \"import secrets; print(secrets.token_urlsafe(32))\"",
                len(_admin_secret),
            )
            import sys; sys.exit(1)

    from app.api.v1.workers.stale_order_cleanup import run_cleanup_loop
    cleanup_task = asyncio.create_task(run_cleanup_loop())

    def _handle_cleanup_crash(t: asyncio.Task):
        if not t.cancelled() and t.exception():
            logger.error("Stale order cleanup worker crashed: %s", t.exception(), exc_info=True)

    cleanup_task.add_done_callback(_handle_cleanup_crash)
    logger.info("🔄 Stale order cleanup loop started")

    yield

    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    logger.info("🛑 Shutting down HoBS API")

# --------------------------------------------------
# Max request body size (defends against giant-payload DoS;
# Railway itself does not cap body size, only headers at 32KB)
# --------------------------------------------------
MAX_REQUEST_BODY_SIZE = int(os.getenv("MAX_REQUEST_BODY_SIZE", 1_000_000))  # 1MB default

class MaxBodySizeMiddleware:
    """
    Raw ASGI middleware (not BaseHTTPMiddleware) so it sits outside everything
    else and can reject before any body is buffered.

    - Fast path: reject immediately if Content-Length header exceeds the limit.
    - Slow path: some clients lie about / omit Content-Length (chunked
      transfer-encoding), so we also count bytes as they stream in via
      receive() and abort mid-stream if the running total goes over.
    """
    def __init__(self, app, max_size: int = MAX_REQUEST_BODY_SIZE):
        self.app = app
        self.max_size = max_size

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                if int(content_length) > self.max_size:
                    response = JSONResponse(
                        status_code=413,
                        content={"detail": f"Request body too large (max {self.max_size} bytes)"},
                    )
                    await response(scope, receive, send)
                    return
            except ValueError:
                pass  # malformed header — let downstream handle it

        total = 0
        limit = self.max_size

        async def limited_receive():
            nonlocal total
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > limit:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Request body too large (max {limit} bytes)",
                    )
            return message

        await self.app(scope, limited_receive, send)

# --------------------------------------------------
# App Initialization
# --------------------------------------------------
app = FastAPI(
    title="HoBS API",
    lifespan=lifespan,
)

# Must be added before CORSMiddleware so it wraps outermost and rejects
# oversized bodies before any other middleware or route touches them.
app.add_middleware(MaxBodySizeMiddleware)

# --------------------------------------------------
# MIDDLEWARES
# --------------------------------------------------

_raw_origins = os.getenv("ALLOWED_ORIGINS", "")
_allow_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]
_env = os.getenv("ENVIRONMENT", "production").lower()

if not _allow_origins:
    if _env == "local":
        _allow_origins = ["*"]
        logger.warning("CORS is open — acceptable for local dev only")
    else:
        import sys
        logger.critical("ALLOWED_ORIGINS not set — refusing to start in production. "
                        "Set ALLOWED_ORIGINS in Railway Variables.")
        sys.exit(1)

if "*" in _allow_origins and _env != "local":
    import sys
    logger.critical("ALLOWED_ORIGINS is wildcard (*) in production — refusing to start.")
    sys.exit(1)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(TenantMiddleware)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(
        "Unhandled exception: %s %s — %s",
        request.method, request.url.path, exc, exc_info=True,
    )
    if _SENTRY_DSN:
        # FastApiIntegration/StarletteIntegration normally auto-capture
        # unhandled exceptions, but registering our own catch-all handler
        # here is exactly the scenario worth being explicit about rather
        # than trusting auto-instrumentation silently — same reasoning as
        # firing the Slack alert explicitly right below.
        import sentry_sdk
        sentry_sdk.capture_exception(exc)
    try:
        from app.infrastructure.alerting.slack import alert
        asyncio.create_task(alert(
            title="Unhandled 500 Error",
            detail=f"`{request.method} {request.url.path}` raised an unhandled exception.",
            level="critical",
            fields={"error": str(exc)[:300]},
        ))
    except Exception:
        pass
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})

@app.middleware("http")
async def trace_all_requests(request: Request, call_next):
    logger.info(f"🌐 {request.method} {request.url.path}")
    response = await call_next(request)
    return response

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: https:; "
        "connect-src 'self'; "
        "frame-ancestors 'none';"
    )
    return response

# --------------------------------------------------
# Routers
# --------------------------------------------------

# ── Core bot & payment infrastructure ─────────────────────────────────────────
from app.api.v1.webhook import router as webhooks_router
from app.api.v1.paystack import router as paystack_router  # RETIRED — kept mounted for rollback, see docs/WIRING_NOTES.md
from app.api.v1.flutterwave_booking import router as flutterwave_booking_router
from app.api.v1.flutterwave_orders import router as flutterwave_orders_router
from app.api.v1.hotel_webhook import router as hotel_webhook_router
from app.api.v1.hotel_dashboard import router as hotel_dashboard_router
from app.api.v1.hotel_staff_auth import router as hotel_staff_auth_router
from app.api.v1.payment import router as payments_router
from app.api.v1.checkout import router as checkout_router

# ── Merchant (identity, auth, onboarding wizard, apply) ───────────────────────
from app.api.v1.merchant import router as merchant_router
# auth.py: /auth/login — SUPERSEDED by /merchants/login in merchant.py.
# merchant.py login is richer (must_change_password flag, longer lockout message).
# Deliberately NOT mounted to avoid a duplicate unauthenticated login surface.

# ── Merchant WhatsApp onboarding (admin + merchant-facing) ────────────────────
from app.api.v1.admin_whatsapp import router as admin_whatsapp_router
from app.api.v1.admin_whatsapp import merchant_router as onboarding_router

# ── Merchant credential management ────────────────────────────────────────────
# admin.py (prefix /merchant-credentials) and client_whatsapp_credential.py
# (prefix /whatsapp-credentials) expose overlapping CRUD on the same
# ClientWhatsAppCredential table but under different prefixes and with
# different auth patterns. admin.py is the older version; client_whatsapp_credential
# is the current one (mounted as whatsapp_cred_router below).
# admin.py is NOT mounted — its routes are all covered by whatsapp_cred_router.
#
# credential.py (prefix /whatsapp-routing) is a read-only subset of
# client_whatsapp_credential. Also NOT mounted — use /whatsapp-credentials instead.
from app.api.v1.client_whatsapp_credential import router as whatsapp_cred_router

# ── Store / client management ──────────────────────────────────────────────────
from app.api.v1.client_api import router as client_router
from app.api.v1.subaccount import router as subaccount_router

# ── Inventory & products ───────────────────────────────────────────────────────
from app.api.v1.inventory import router as inventory_router
from app.api.v1.product import router as product_router

# ── Orders & fulfillment ───────────────────────────────────────────────────────
from app.api.v1.orders_api import router as orders_router
# order_fulfillment.py exposed POST /orders/confirm-pickup/{order_code} — a
# webhook-style route called with a WhatsApp number to confirm cash pickup.
# orders_api.py covers the dashboard confirm-cash flow (POST /{order_id}/confirm-cash).
# confirm-pickup is a DIFFERENT operation (used by the bot/payment orchestrator
# internally via OrderFulfillmentService.confirm_pickup()). It is NOT called
# by the dashboard frontend. Mounting it would expose an unauthenticated endpoint
# that can mark any order FULFILLED given just an order_code + phone number.
# NOT mounted — the service method is called directly from payment_orchestrator.py.

# ── Cart ───────────────────────────────────────────────────────────────────────
# cart.py (prefix /cart) — CRUD on cart/cart-items used during the bot ordering
# flow. The bot calls CartService directly through orchestrators, not via HTTP.
# No dashboard or frontend page calls /cart/* — confirmed by template audit.
# Mounting it would expose unauthenticated cart manipulation endpoints.
# NOT mounted — internal use only via service layer.
from app.api.v1.cart import router as cart_router  # imported for completeness; see below

# ── Human agent escalation ────────────────────────────────────────────────────
# human_agent.py (prefix /human-agent) — task queue for bot→human handoff.
# HumanAgentService is called directly from the conversation orchestrator.
# No frontend page or external caller uses these HTTP endpoints.
# Mounting it would expose unauthenticated task creation/mutation.
# NOT mounted — internal use only via service layer.
from app.api.v1.human_agent import router as human_agent_router  # imported for completeness; see below

# ── Admin & internal ops ───────────────────────────────────────────────────────
from app.api.v1.debug import router as debug_router
from app.api.v1.internal_cron import router as internal_cron_router

API_V1_PREFIX = "/api/v1"

# Webhook & payment (order matters — webhooks before everything else)
app.include_router(webhooks_router,  prefix=API_V1_PREFIX, tags=["Webhooks"])
app.include_router(paystack_router,  prefix=API_V1_PREFIX, tags=["Paystack"])  # RETIRED — see docs/WIRING_NOTES.md
app.include_router(flutterwave_booking_router, prefix=API_V1_PREFIX, tags=["Flutterwave Bookings"])
app.include_router(flutterwave_orders_router, prefix=API_V1_PREFIX, tags=["Flutterwave Orders"])
app.include_router(hotel_webhook_router, prefix=API_V1_PREFIX, tags=["Hotel WhatsApp Webhook"])
app.include_router(hotel_dashboard_router, prefix=API_V1_PREFIX, tags=["Hotel Dashboard"])
app.include_router(hotel_staff_auth_router, prefix=API_V1_PREFIX, tags=["Hotel Staff Auth"])

# Merchant identity & onboarding
app.include_router(merchant_router,  prefix=API_V1_PREFIX, tags=["Merchants"])

# WhatsApp setup (admin dashboard + merchant self-serve; carry their own prefixes)
app.include_router(admin_whatsapp_router)
app.include_router(onboarding_router)

# Credentials / routing
app.include_router(whatsapp_cred_router, prefix=API_V1_PREFIX, tags=["WhatsApp Credentials"])

# Store management
app.include_router(client_router,    prefix=API_V1_PREFIX, tags=["Clients"])
app.include_router(subaccount_router, prefix=API_V1_PREFIX, tags=["Subaccounts"])

# Catalogue
app.include_router(inventory_router, prefix=API_V1_PREFIX, tags=["Inventory"])
app.include_router(product_router,   prefix=API_V1_PREFIX, tags=["Products"])

# Orders & payments
app.include_router(orders_router,    prefix=API_V1_PREFIX, tags=["Orders"])
app.include_router(payments_router,  prefix=API_V1_PREFIX, tags=["Payments"])
app.include_router(checkout_router,  prefix=API_V1_PREFIX, tags=["Checkout"])

# Ops
app.include_router(debug_router,         prefix=API_V1_PREFIX, tags=["Debug"])
app.include_router(internal_cron_router)

# NOTE: cart_router, human_agent_router, order_fulfillment confirm-pickup,
# auth_router, admin_router, and credential_router are intentionally NOT mounted.
# See per-router comments in the imports section above for the rationale.

# --------------------------------------------------
# Health & Root
# --------------------------------------------------

# Frontend (Next.js) base URL — used by every route below that's been retired
# in favor of its Next.js equivalent. Nothing in this backend links to these
# routes anymore (emails/redirects all point at the frontend already); they
# only exist so old bookmarks/links don't 404.
APP_URL = os.getenv("APP_URL", "https://hobs.altekflo.xyz").rstrip("/")

@app.get("/")
async def root():
    """Retired — the real landing page is the Next.js app at APP_URL."""
    return RedirectResponse(url=APP_URL, status_code=308)

@app.get("/health")
async def health():
    return {"status": "healthy"}


# ── Merchant dashboard ─────────────────────────────────────────────────────────
# Retired — the real dashboard is the Next.js app's /dashboard page. Every
# email that used to link here already points at APP_URL/dashboard, so this
# route (and its old static file mount) is only kept to redirect stragglers.

@app.get("/dashboard")
async def dashboard_index(request: Request):
    qs = f"?{request.url.query}" if request.url.query else ""
    return RedirectResponse(url=f"{APP_URL}/dashboard{qs}", status_code=308)


# ── Store (client) pages ───────────────────────────────────────────────────────
# Retired — both live in the Next.js app now. Kept only to redirect old links.

@app.get("/store-login")
async def store_login_page(request: Request):
    qs = f"?{request.url.query}" if request.url.query else ""
    return RedirectResponse(url=f"{APP_URL}/store-login{qs}", status_code=308)


@app.get("/store-dashboard")
async def store_dashboard_page(request: Request):
    qs = f"?{request.url.query}" if request.url.query else ""
    return RedirectResponse(url=f"{APP_URL}/store-dashboard{qs}", status_code=308)


# ── Apply-flow follow-up page ───────────────────────────────────────────────────
# Linked from the apply-confirmation email when no WhatsApp number was given.
# Public, token-driven (?token=...) — see GET/POST /merchants/apply/link/{token}.

@app.get("/apply/whatsapp-number/{token}", response_class=HTMLResponse)
async def apply_add_whatsapp_number_page(token: str):
    _tpl = os.path.join(os.path.dirname(__file__), "templates", "add_whatsapp_number.html")
    with open(_tpl, "r") as f:
        return HTMLResponse(content=f.read())


# ── Global static assets ───────────────────────────────────────────────────────
_static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=_static_dir), name="static")


@app.get("/payment-success")
async def payment_success(request: Request):
    """
    Retired — PAYSTACK_REDIRECT_URL is configured to send customers straight
    to the Next.js app's /payment-success page, so this route isn't part of
    the live checkout flow. Kept only to redirect any stale/cached links,
    preserving query params (ref, wa, status) the frontend page reads.
    """
    qs = f"?{request.url.query}" if request.url.query else ""
    return RedirectResponse(url=f"{APP_URL}/payment-success{qs}", status_code=308)
