import re
import logging
from typing import Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _normalise_phone(raw: str) -> str:
    """
    Strip all non-digit characters, drop a leading '+', and ensure the result
    is 7–15 digits (ITU-T E.164 range without the leading +).
    Returns the normalised string, or raises ValueError on bad input.
    """
    digits = re.sub(r"\D", "", raw)
    if not digits:
        raise ValueError("Phone number is required.")
    if len(digits) < 7 or len(digits) > 15:
        raise ValueError("Enter a valid phone number (7–15 digits).")
    return digits


# ─────────────────────────────────────────────────────────────────────────────
# Merchant schemas
# ─────────────────────────────────────────────────────────────────────────────

class MerchantCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr
    password: str = Field(..., min_length=6)
    whatsapp_number: Optional[str] = None

    @field_validator("whatsapp_number", mode="before")
    @classmethod
    def normalise_whatsapp(cls, v):
        if not v:
            return None
        return _normalise_phone(str(v))


class MerchantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    email: str
    email_verified: bool
    whatsapp_number: Optional[str] = None
    waba_active: bool


class MerchantUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    whatsapp_number: Optional[str] = None

    @field_validator("whatsapp_number", mode="before")
    @classmethod
    def normalise_whatsapp(cls, v):
        if not v:
            return None
        return _normalise_phone(str(v))


class MerchantLogin(BaseModel):
    email: EmailStr
    password: str


# ─────────────────────────────────────────────────────────────────────────────
# Application schemas  (POST /merchants/apply — legacy single-page form)
# ─────────────────────────────────────────────────────────────────────────────

class MerchantApply(BaseModel):
    """Legacy single-step application form (still live on the landing page)."""
    business_name: str = Field(..., min_length=1, max_length=255)
    business_type: str = Field(..., min_length=1, max_length=100)
    city_state: str = Field(..., min_length=1, max_length=150)
    full_name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr
    phone_number: str
    whatsapp_number: Optional[str] = None
    num_branches: int = Field(default=1, ge=1)
    monthly_order_volume: Optional[str] = None
    uses_whatsapp_manual: bool = False
    uses_delivery_service: bool = False
    heard_about_us: Optional[str] = Field(None, max_length=200)
    comments: Optional[str] = None
    # Honeypot — bots fill this; real users don't see it
    website: Optional[str] = None

    @field_validator("phone_number", mode="before")
    @classmethod
    def normalise_phone(cls, v):
        return _normalise_phone(str(v))

    @field_validator("whatsapp_number", mode="before")
    @classmethod
    def normalise_whatsapp(cls, v):
        if not v:
            return None
        return _normalise_phone(str(v))


# ─────────────────────────────────────────────────────────────────────────────
# Onboarding wizard schemas  (4-step flow at /merchants/apply/start)
# ─────────────────────────────────────────────────────────────────────────────

class ApplyStepOne(BaseModel):
    """Step 1: contact details — creates a draft application."""
    full_name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr
    phone_number: str
    whatsapp_number: Optional[str] = None
    # Honeypot
    website: Optional[str] = None

    @field_validator("phone_number", mode="before")
    @classmethod
    def normalise_phone(cls, v):
        return _normalise_phone(str(v))

    @field_validator("whatsapp_number", mode="before")
    @classmethod
    def normalise_whatsapp(cls, v):
        if not v:
            return None
        return _normalise_phone(str(v))


class ApplyStepTwo(BaseModel):
    """Step 2: business details."""
    business_name: str = Field(..., min_length=1, max_length=255)
    business_type: str = Field(..., min_length=1, max_length=100)
    city_state: str = Field(..., min_length=1, max_length=150)
    registration_status: str = Field(..., pattern=r"^(registered|unregistered)$")
    num_branches: int = Field(default=1, ge=1)
    monthly_order_volume: Optional[str] = None
    uses_whatsapp_manual: bool = False
    uses_delivery_service: bool = False
    heard_about_us: Optional[str] = Field(None, max_length=200)
    comments: Optional[str] = None


class ApplyStepThree(BaseModel):
    """Step 3: identity / business verification."""
    # Registered businesses supply a CAC number; unregistered use BVN or NIN.
    # Verification is optional — applicants can skip it and finish the wizard
    # anyway. skip_verification=True is the explicit "I'll do this later"
    # path; see apply_wizard_step_three in api/v1/merchant.py for what that
    # sets in motion (7-day reminder sequence, eventual admin nudge).
    cac_number: Optional[str] = None
    verification_method: Optional[str] = Field(None, pattern=r"^(bvn|nin)$")
    bvn: Optional[str] = None
    nin: Optional[str] = None
    skip_verification: bool = False


class ApplyStepFour(BaseModel):
    """Step 4: terms & indemnity acceptance — finalises the application."""
    terms_version: str = Field(..., min_length=1, max_length=20)
