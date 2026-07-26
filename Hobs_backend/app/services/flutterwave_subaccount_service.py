# app/services/flutterwave_subaccount_service.py
#
# See docs/WIRING_NOTES.md before touching this file.
#
# This calls the REAL Flutterwave API (api.flutterwave.com), unlike
# app/services/paystack_subaccount_service.py which — despite writing to
# the same FlutterwaveSubaccount model — actually calls Paystack's API.
# Do not confuse the two.

import os
import logging
import httpx
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.flutterwave_subaccount import FlutterwaveSubaccount

logger = logging.getLogger(__name__)
FLUTTERWAVE_BASE = "https://api.flutterwave.com/v3"


class FlutterwaveSubaccountService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _headers(self) -> dict:
        # Deliberately reads PAYSTACK_SECRET_KEY — see docs/WIRING_NOTES.md.
        # This env var actually holds the Flutterwave secret key in this deployment.
        secret = os.getenv("PAYSTACK_SECRET_KEY")
        if not secret:
            raise ValueError("PAYSTACK_SECRET_KEY not configured (holds the Flutterwave secret key — see docs/WIRING_NOTES.md)")
        return {"Authorization": f"Bearer {secret}", "Content-Type": "application/json"}

    async def list_banks(self, country: str = "NG") -> list:
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.get(
                f"{FLUTTERWAVE_BASE}/banks/{country}",
                headers=self._headers(),
            )
        data = res.json()
        if data.get("status") != "success":
            raise ValueError("Could not fetch banks from Flutterwave")
        return sorted(
            [{"code": b["code"], "name": b["name"]} for b in data.get("data", [])],
            key=lambda b: b["name"],
        )

    async def verify_account(self, account_number: str, bank_code: str) -> dict:
        payload = {"account_number": account_number, "account_bank": bank_code}
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.post(
                f"{FLUTTERWAVE_BASE}/accounts/resolve",
                json=payload,
                headers=self._headers(),
            )
        data = res.json()
        if data.get("status") != "success":
            raise ValueError(data.get("message", "Could not verify account"))
        return {
            "account_name": data["data"]["account_name"],
            "account_number": account_number,
            "bank_code": bank_code,
        }

    async def register(
        self,
        *,
        client_id: str,
        merchant_id: str,
        account_bank: str,
        account_number: str,
        account_name: str,
        business_name: str,
        split_percentage: float = 5.0,
    ) -> FlutterwaveSubaccount:
        """
        split_percentage is the PLATFORM's cut (defaults to 5%) — Flutterwave's
        subaccount `split_value` field is what the platform takes, the rest
        settles to the hotel automatically. Confirm this matches your actual
        commercial terms before going live; 5% here is a placeholder, not a
        pricing decision made on your behalf.
        """
        payload = {
            "account_bank": account_bank,
            "account_number": account_number,
            "business_name": business_name,
            "business_email": f"{client_id}@hobs.app",
            "country": "NG",
            "split_type": "percentage",
            "split_value": split_percentage / 100,
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            res = await client.post(
                f"{FLUTTERWAVE_BASE}/subaccounts",
                json=payload,
                headers=self._headers(),
            )
        data = res.json()
        if data.get("status") != "success":
            raise ValueError(f"Flutterwave subaccount error: {data.get('message', 'Unknown error')}")

        subaccount_id = data["data"]["subaccount_id"]
        logger.info("Flutterwave subaccount created: %s for client %s", subaccount_id, client_id)

        subaccount = FlutterwaveSubaccount(
            client_id=client_id,
            merchant_id=merchant_id,
            subaccount_id=str(subaccount_id),
            account_bank=account_bank,
            account_number=account_number,
            business_name=business_name,
            split_value=str(split_percentage / 100),
            split_type="percentage",
            active=True,
        )
        self.db.add(subaccount)
        await self.db.flush()
        return subaccount

    async def get_for_client(self, client_id: str, merchant_id: str) -> Optional[FlutterwaveSubaccount]:
        result = await self.db.execute(
            select(FlutterwaveSubaccount).where(
                FlutterwaveSubaccount.client_id == client_id,
                FlutterwaveSubaccount.merchant_id == merchant_id,
                FlutterwaveSubaccount.active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def get_subaccount_id(self, client_id: str, merchant_id: str) -> Optional[str]:
        sub = await self.get_for_client(client_id, merchant_id)
        return sub.subaccount_id if sub else None

    async def deactivate(self, client_id: str, merchant_id: str) -> bool:
        result = await self.db.execute(
            select(FlutterwaveSubaccount).where(
                FlutterwaveSubaccount.client_id == client_id,
                FlutterwaveSubaccount.merchant_id == merchant_id,
            )
        )
        subaccount = result.scalar_one_or_none()
        if not subaccount:
            return False
        await self.db.delete(subaccount)
        await self.db.flush()
        return True
