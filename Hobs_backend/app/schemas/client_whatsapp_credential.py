from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import Optional
from datetime import datetime


# ─────────────────────────────────────────────────────────────────────────────
# Status constants — mirror the model's CREDENTIAL_STATUS_* values
# ─────────────────────────────────────────────────────────────────────────────
VALID_STATUSES = frozenset({"pending", "otp_sent", "otp_verified", "active"})


# =============================================================================
# CREATE (write-once — admin only)
# =============================================================================
class ClientWhatsAppCredentialCreate(BaseModel):
    client_id: str = Field(
        ...,
        min_length=8,
        max_length=8,
        pattern=r'^ST[A-Z0-9]{6}$',
        description="Client/Store ID (ST + 6 alphanumeric chars, e.g. STAB1234)",
    )
    phone_number_id: str = Field(
        ...,
        min_length=3,
        description="Meta-issued WhatsApp Phone Number ID for this number",
    )
    whatsapp_number: Optional[str] = Field(
        None,
        description="The phone number in local format e.g. 2348012345678",
    )
    status: str = Field(
        default="pending",
        description="Onboarding state: pending | otp_sent | otp_verified | active",
    )
    # active is derived from status — only set explicitly when back-filling old data
    active: bool = Field(
        default=False,
        description="True only when status='active'. Normally set automatically.",
    )
    business_account_id: Optional[str] = Field(None, description="Meta Business Account ID")
    waba_id:             Optional[str] = Field(None, description="WhatsApp Business Account ID")

    @field_validator("phone_number_id")
    @classmethod
    def strip_phone_number_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("phone_number_id cannot be empty")
        return v.strip()

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in VALID_STATUSES:
            raise ValueError(f"status must be one of: {', '.join(sorted(VALID_STATUSES))}")
        return v

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "client_id":        "STAB1234",
                "phone_number_id":  "123456789012345",
                "whatsapp_number":  "2348012345678",
                "status":           "pending",
                "active":           False,
            }
        },
    )


# =============================================================================
# UPDATE
# =============================================================================
class ClientWhatsAppCredentialUpdate(BaseModel):
    phone_number_id:     Optional[str]  = Field(None, min_length=3)
    whatsapp_number:     Optional[str]  = None
    status:              Optional[str]  = Field(
        None,
        description="Onboarding state: pending | otp_sent | otp_verified | active",
    )
    active:              Optional[bool] = None
    business_account_id: Optional[str]  = None
    waba_id:             Optional[str]  = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v):
        if v is not None and v not in VALID_STATUSES:
            raise ValueError(f"status must be one of: {', '.join(sorted(VALID_STATUSES))}")
        return v

    model_config = ConfigDict(extra="forbid")


# =============================================================================
# FULL RESPONSE (admin endpoints)
# =============================================================================
class ClientWhatsAppCredentialOut(BaseModel):
    client_id:           str
    phone_number_id:     str
    whatsapp_number:     Optional[str]      = None
    status:              str                = "pending"
    active:              bool
    business_account_id: Optional[str]      = None
    waba_id:             Optional[str]      = None
    created_at:          datetime

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "client_id":        "STAB1234",
                "phone_number_id":  "123456789012345",
                "whatsapp_number":  "2348012345678",
                "status":           "otp_sent",
                "active":           False,
                "created_at":       "2024-01-15T10:30:00Z",
            }
        },
    )


# =============================================================================
# SUMMARY (list endpoints — admin dashboard table)
# =============================================================================
class ClientWhatsAppCredentialSummary(BaseModel):
    client_id:       str
    phone_number_id: str
    whatsapp_number: Optional[str] = None
    status:          str           = "pending"
    active:          bool
    created_at:      datetime

    model_config = ConfigDict(from_attributes=True)


# =============================================================================
# SIMPLE (embedded inside ClientOut — merchant-facing)
# Shows status so the merchant dashboard can render the right UI state.
# =============================================================================
class ClientWhatsAppCredentialSimple(BaseModel):
    phone_number_id: str
    whatsapp_number: Optional[str] = None
    status:          str           = "pending"
    active:          bool

    model_config = ConfigDict(from_attributes=True)


# =============================================================================
# ROUTING INFO (internal — WhatsApp send pipeline)
# =============================================================================
class WhatsAppRoutingInfo(BaseModel):
    phone_number_id:     str
    client_id:           str
    whatsapp_number:     Optional[str] = None
    business_account_id: Optional[str] = None
    waba_id:             Optional[str] = None

    model_config = ConfigDict(from_attributes=True, extra="ignore")
