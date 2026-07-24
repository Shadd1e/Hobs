from typing import Optional, List
import random
import secrets
import string
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models.merchant import Merchant
from app.schemas.merchant import MerchantCreate
from app.core.security import get_password_hash, verify_password
import logging

logger = logging.getLogger(__name__)

MAX_FAILED_ATTEMPTS = 6
CODE_EXPIRY_MINUTES = 30


def _generate_code() -> str:
    """Generate a 6-digit numeric verification code."""
    return f"{random.randint(0, 999999):06d}"


class MerchantService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _generate_merchant_id(self) -> str:
        """Generate a random Merchant ID e.g. MXA3F7K2."""
        alphabet = string.ascii_uppercase + string.digits
        for _ in range(20):
            candidate = "MX" + "".join(secrets.choice(alphabet) for _ in range(6))
            exists = await self.db.execute(
                select(Merchant.id).where(Merchant.id == candidate)
            )
            if not exists.scalar_one_or_none():
                return candidate
        raise RuntimeError("Failed to generate unique merchant ID after 20 attempts")

    async def _generate_client_id(self) -> str:
        """Generate a random Store ID e.g. STA3F7K2."""
        from app.models.client_model import Client
        alphabet = string.ascii_uppercase + string.digits
        for _ in range(20):
            candidate = "ST" + "".join(secrets.choice(alphabet) for _ in range(6))
            exists = await self.db.execute(
                select(Client.id).where(Client.id == candidate)
            )
            if not exists.scalar_one_or_none():
                return candidate
        raise RuntimeError("Failed to generate unique client ID after 20 attempts")

    async def create(self, payload: MerchantCreate) -> Optional[Merchant]:
        """
        Create a new merchant + their first default store.

        whatsapp_number from the registration form is stored on both
        the Merchant record (for quick admin dashboard lookup) and on the
        auto-created Client record (so the store is pre-populated).
        """
        existing = await self.db.execute(
            select(Merchant).where(Merchant.email == payload.email)
        )
        if existing.scalars().first():
            return None

        merchant_id = await self._generate_merchant_id()
        client_id   = await self._generate_client_id()
        code        = _generate_code()
        expiry      = datetime.now(timezone.utc) + timedelta(minutes=CODE_EXPIRY_MINUTES)

        merchant = Merchant(
            id=merchant_id,
            name=payload.name,
            email=payload.email,
            password_hash=get_password_hash(payload.password),
            failed_attempts=0,
            email_verified=False,
            email_verification_token=code,
            email_verification_token_expiry=expiry,
            waba_active=False,
            # Store the submitted number so admin can see it without joining
            whatsapp_number=payload.whatsapp_number,
        )
        self.db.add(merchant)

        # Auto-create the merchant's first store, pre-populated with their number.
        # WhatsApp is not active yet — that happens through the admin onboarding flow.
        from app.models.client_model import Client
        client = Client(
            id=client_id,
            name=payload.name,
            merchant_id=merchant_id,
            # Store the number for display; it's not live until credential is active
            whatsapp_number=payload.whatsapp_number,
            store_contact_number=None,
        )
        self.db.add(client)

        # Stash client_id on the merchant object so the API layer can
        # include it in the verification email without an extra DB query.
        merchant._auto_client_id = client_id

        return merchant

    async def verify_email_code(self, merchant_id: str, code: str) -> tuple[bool, str]:
        """
        Verify a 6-digit code for the given merchant.
        Returns (success: bool, reason: str)
        """
        merchant = await self.get(merchant_id)
        if not merchant:
            return False, "Merchant not found"

        if merchant.email_verified:
            return True, "already_verified"

        if not merchant.email_verification_token:
            return False, "No code found. Request a new one."

        expiry = merchant.email_verification_token_expiry
        if expiry and datetime.now(timezone.utc) > expiry:
            return False, "This code has expired. Request a new one."

        if merchant.email_verification_token != code.strip():
            return False, "Incorrect code. Check your email and try again."

        merchant.email_verified                  = True
        merchant.email_verification_token        = None
        merchant.email_verification_token_expiry = None
        return True, "ok"

    async def refresh_verification_code(self, merchant_id: str) -> Optional[str]:
        """Generate a fresh code and expiry. Returns the new code."""
        merchant = await self.get(merchant_id)
        if not merchant or merchant.email_verified:
            return None
        code   = _generate_code()
        expiry = datetime.now(timezone.utc) + timedelta(minutes=CODE_EXPIRY_MINUTES)
        merchant.email_verification_token        = code
        merchant.email_verification_token_expiry = expiry
        return code

    async def get(self, merchant_id: str) -> Optional[Merchant]:
        res = await self.db.execute(
            select(Merchant).where(Merchant.id == merchant_id)
        )
        return res.scalars().first()

    async def list_all(self) -> List[Merchant]:
        res = await self.db.execute(select(Merchant))
        return res.scalars().all()

    async def update(self, merchant_id: str, payload: dict) -> Optional[Merchant]:
        merchant = await self.get(merchant_id)
        if not merchant:
            return None
        for key, value in payload.items():
            if key == "password" and value:
                merchant.password_hash = get_password_hash(value)
            elif hasattr(merchant, key):
                setattr(merchant, key, value)
        return merchant

    async def delete(self, merchant_id: str) -> bool:
        merchant = await self.get(merchant_id)
        if not merchant:
            return False
        await self.db.delete(merchant)
        return True

    async def authenticate(
        self,
        email: str,
        password: str,
    ) -> Optional[Merchant]:
        result = await self.db.execute(
            select(Merchant).where(Merchant.email == email)
        )
        merchant = result.scalars().first()
        if not merchant:
            return None
        if merchant.failed_attempts >= MAX_FAILED_ATTEMPTS:
            return None
        if verify_password(password, merchant.password_hash):
            # FIX: removed email_verified gate. Previously an unverified merchant
            # would receive "Invalid credentials" with no explanation — now they
            # log in and the frontend/dashboard shows the verification prompt.
            # email_verified is returned in the login response so the UI can gate features.
            merchant.failed_attempts = 0
            return merchant
        merchant.failed_attempts += 1
        return None

    async def is_email_verified(self, merchant_id: str) -> bool:
        merchant = await self.get(merchant_id)
        return bool(merchant and merchant.email_verified)
