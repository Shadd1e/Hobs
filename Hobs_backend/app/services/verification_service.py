# app/services/verification_service.py
"""
CAC / BVN / NIN verification.

IMPORTANT — this is a stub, not a real integration. We don't have credentials
for an identity-verification provider yet, so this module deliberately does
NOT fabricate a working check against a real API. Instead it gives you one
clean place to plug a provider in later (e.g. Dojah, YouVerify, Smile
Identity, Prembly, or Paystack's own BVN-match endpoint).

Until a provider is wired in, every check returns "pending_manual_review" —
the application still moves forward (so onboarding isn't blocked), but it's
flagged for a human at your end to actually check the CAC/BVN/NIN before
the transaction limit gets bumped up from the conservative default.

To wire in a real provider:
  1. Add the provider's API key as an env var (e.g. IDENTITY_PROVIDER_API_KEY).
  2. Replace the body of verify_cac / verify_bvn / verify_nin below with a
     real httpx call to that provider, mapping their response onto
     VerificationResult.
  3. Nothing else needs to change — app/api/v1/merchant.py only calls these
     three functions and reads .status / .name_on_file off the result.
"""
import logging
import os
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class VerificationResult:
    status: str                       # "verified" | "pending_manual_review" | "failed"
    name_on_file: Optional[str] = None  # name the provider returned, if any
    reason: Optional[str] = None        # why it failed, if status == "failed"


def _provider_configured() -> bool:
    return bool(os.getenv("IDENTITY_PROVIDER_API_KEY", ""))


async def verify_cac(rc_number: str, business_name: str) -> VerificationResult:
    """Verify a CAC RC/BN number against the business name on the application."""
    if not _provider_configured():
        logger.info("IDENTITY_PROVIDER_API_KEY not set — CAC check for %s queued for manual review", rc_number)
        return VerificationResult(status="pending_manual_review")

    # TODO: real CAC lookup call goes here once a provider is chosen.
    raise NotImplementedError("CAC verification provider not yet integrated.")


async def verify_bvn(bvn: str, full_name: str) -> VerificationResult:
    """Verify a BVN against the applicant's full name."""
    if not _provider_configured():
        logger.info("IDENTITY_PROVIDER_API_KEY not set — BVN check queued for manual review")
        return VerificationResult(status="pending_manual_review")

    # TODO: real BVN lookup call goes here once a provider is chosen.
    raise NotImplementedError("BVN verification provider not yet integrated.")


async def verify_nin(nin: str, full_name: str) -> VerificationResult:
    """Verify a NIN against the applicant's full name."""
    if not _provider_configured():
        logger.info("IDENTITY_PROVIDER_API_KEY not set — NIN check queued for manual review")
        return VerificationResult(status="pending_manual_review")

    # TODO: real NIN lookup call goes here once a provider is chosen.
    raise NotImplementedError("NIN verification provider not yet integrated.")


# ─────────────────────────────────────────────────────────────────────────────
# Transaction limits by verification outcome.
# Placeholder values — tune these to whatever your actual risk appetite is.
# Numbers are monthly transaction volume caps in Naira.
# ─────────────────────────────────────────────────────────────────────────────
TRANSACTION_LIMITS = {
    ("registered", "verified"):               5_000_000.00,
    ("registered", "pending_manual_review"):  1_000_000.00,
    ("unregistered", "verified"):                500_000.00,
    ("unregistered", "pending_manual_review"):   150_000.00,
}


def get_transaction_limit(registration_status: str, verification_status: str) -> float:
    return TRANSACTION_LIMITS.get((registration_status, verification_status), 50_000.00)
