import logging
logger = logging.getLogger(__name__)

# app/core/security.py
from datetime import datetime, timedelta
import jwt as pyjwt
from jwt.exceptions import DecodeError, ExpiredSignatureError
from passlib.context import CryptContext
from app.core.config import settings

# ================================================================
# 🔐 PASSWORD HASHING
# ================================================================
# Use Argon2 (modern, secure, no 72-byte limit)
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


def hash_password(password: str) -> str:
    """Securely hash a plaintext password."""
    return pwd_context.hash(password)


def get_password_hash(password: str) -> str:
    """Alias for hash_password."""
    return hash_password(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Check if the provided password matches the stored hash."""
    return pwd_context.verify(plain_password, hashed_password)


# ================================================================
# 🔑 JWT TOKEN UTILITIES
# ================================================================
def create_access_token(subject: str) -> str:
    """Generate a merchant JWT token. Payload: { sub: merchant_id }."""
    expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode = {"exp": expire, "sub": str(subject)}
    return pyjwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_client_access_token(client_id: str, merchant_id: str) -> str:
    """
    Generate a store-scoped JWT for client dashboard login.

    Payload shape:
        { "sub": client_id, "merchant_id": merchant_id, "type": "client", "exp": ... }

    The middleware and get_current_merchant() already handle dict payloads —
    merchant_id flows through normally so all existing endpoint guards keep working.
    """
    expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode = {
        "exp":         expire,
        "sub":         client_id,
        "merchant_id": merchant_id,
        "type":        "client",
    }
    return pyjwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_staff_access_token(staff_id: str, client_id: str, merchant_id: str) -> str:
    """
    Generate a staff-scoped JWT for individual HotelStaff (manager/top_manager)
    dashboard login — distinct from create_client_access_token, which is
    scoped to the store/client account as a whole, not an individual staff
    member.

    Payload shape:
        { "sub": staff_id, "client_id": client_id, "merchant_id": merchant_id,
          "type": "staff", "exp": ... }

    decode_access_token() only special-cases "client" tokens today — staff
    tokens fall through to the plain-string branch and would return the raw
    payload dict's "sub" (the staff_id) rather than the fuller staff context.
    Callers that need client_id/merchant_id from a staff token should decode
    the raw JWT directly (pyjwt.decode) rather than relying on
    decode_access_token() until that function is extended with a "staff"
    branch, mirroring the "client" one above.
    """
    expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode = {
        "exp":         expire,
        "sub":         staff_id,
        "client_id":   client_id,
        "merchant_id": merchant_id,
        "type":        "staff",
    }
    return pyjwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> str | dict | None:
    """
    Decode a JWT token.

    Returns:
        - str   → plain merchant token (legacy shape: { sub: merchant_id })
        - dict  → client token shape: { sub, merchant_id, type }
        - dict  → staff token shape: { sub, client_id, merchant_id, type }
        - None  → invalid or expired
    """
    try:
        payload = pyjwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        token_type = payload.get("type")

        if token_type == "client":
            # Client token — return full dict so middleware can set both IDs
            return {
                "sub":         payload.get("sub"),        # client_id
                "merchant_id": payload.get("merchant_id"),
                "type":        "client",
            }

        if token_type == "staff":
            # Staff token — return full dict so callers can see which staff
            # member is acting, not just which store/client account.
            return {
                "sub":         payload.get("sub"),        # staff_id
                "client_id":   payload.get("client_id"),
                "merchant_id": payload.get("merchant_id"),
                "type":        "staff",
            }

        # Merchant token — return plain merchant_id string (backwards-compat)
        return payload.get("sub")

    except (DecodeError, ExpiredSignatureError, Exception):
        return None


# ================================================================
# 🔒 TOKEN MASKING FOR LOGGING/DISPLAY
# ================================================================
def mask_token(token: str, visible_chars: int = 4) -> str:
    """
    Mask a sensitive token for logging/display purposes.

    Args:
        token: The token to mask (e.g., WhatsApp API token, JWT token)
        visible_chars: Number of characters to show at start and end

    Returns:
        Masked token string (e.g., "abcd...wxyz" or "***" for short tokens)

    Examples:
        >>> mask_token("EAADAZCZBPZBXYZ1234567890")
        "EAAD...7890"
        >>> mask_token("short")
        "***"
    """
    if not token:
        return ""

    token = str(token).strip()
    token_length = len(token)

    if token_length <= visible_chars * 2:
        return "***"

    return f"{token[:visible_chars]}...{token[-visible_chars:]}"


def mask_sensitive_data(data: dict) -> dict:
    """
    Mask sensitive fields in a dictionary for safe logging.

    Args:
        data: Dictionary potentially containing sensitive fields

    Returns:
        Copy of dictionary with sensitive values masked
    """
    if not data:
        return {}

    masked = data.copy()

    # Mask tokens
    for field in ["token", "access_token", "refresh_token", "api_key", "secret"]:
        if field in masked and masked[field]:
            masked[field] = mask_token(masked[field])

    # Mask phone number IDs
    if "phone_number_id" in masked and masked["phone_number_id"]:
        pid = str(masked["phone_number_id"])
        if len(pid) > 6:
            masked["phone_number_id"] = f"{pid[:3]}...{pid[-3:]}"

    return masked
