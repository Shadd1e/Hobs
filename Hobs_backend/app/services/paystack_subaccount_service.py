import os
import logging
import httpx
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.flutterwave_subaccount import FlutterwaveSubaccount

logger = logging.getLogger(__name__)
PAYSTACK_BASE = "https://api.paystack.co"


class PaystackSubaccountService:
    """
    RETIRED / DORMANT as of the Flutterwave order-payment cutover — see
    docs/WIRING_NOTES.md. Nothing in checkout_service.py or
    checkout_orchestrator.py calls this anymore; FlutterwaveSubaccountService
    is the live path for both orders and bookings now. Left in place
    (not deleted) per product decision, in case of rollback. Do not wire
    this back into checkout without also reverting the Flutterwave webhook
    changes — the two need to move together.
    """
    # Platform's default commission when a store doesn't get a custom rate.
    # Was hardcoded to 1.0 everywhere — changed to 0.8 per product decision,
    # and now actually overridable per store (see register()'s
    # percentage_charge param). Paystack's subaccount API only supports a
    # percentage split at the subaccount level (no flat-fee option), so
    # split_type stays "percentage" — see the 400 raised in register()
    # below if a caller asks for "flat".
    DEFAULT_PERCENTAGE_CHARGE = 0.8

    def __init__(self, db: AsyncSession):
        self.db = db

    def _headers(self) -> dict:
        secret = os.getenv("PAYSTACK_SECRET_KEY")
        if not secret:
            raise ValueError("PAYSTACK_SECRET_KEY not configured")
        return {"Authorization": f"Bearer {secret}", "Content-Type": "application/json"}

    async def list_banks(self) -> list:
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.get(
                f"{PAYSTACK_BASE}/bank?currency=NGN&perPage=100",
                headers=self._headers()
            )
        data = res.json()
        if not data.get("status"):
            raise ValueError("Could not fetch banks from Paystack")
        return sorted(
            [{"code": b["code"], "name": b["name"]} for b in data.get("data", [])],
            key=lambda b: b["name"]
        )

    async def verify_account(self, account_number: str, bank_code: str) -> dict:
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.get(
                f"{PAYSTACK_BASE}/bank/resolve"
                f"?account_number={account_number}&bank_code={bank_code}",
                headers=self._headers()
            )
        data = res.json()
        if not data.get("status"):
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
        percentage_charge: Optional[float] = None,
    ) -> FlutterwaveSubaccount:
        if percentage_charge is None:
            percentage_charge = self.DEFAULT_PERCENTAGE_CHARGE
        if not (0 <= percentage_charge <= 100):
            raise ValueError("percentage_charge must be between 0 and 100")

        payload = {
            "business_name": business_name,
            "settlement_bank": account_bank,
            "account_number": account_number,
            "percentage_charge": percentage_charge,
            "description": f"ShopprHQ store {client_id}",
            "primary_contact_email": f"{client_id}@shopprhq.app",
            "primary_contact_name": account_name,  # real bank account holder name for Paystack verification
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            res = await client.post(
                f"{PAYSTACK_BASE}/subaccount",
                json=payload,
                headers=self._headers()
            )
        data = res.json()
        if not data.get("status"):
            raise ValueError(f"Paystack subaccount error: {data.get('message', 'Unknown error')}")
        subaccount_code = data["data"]["subaccount_code"]
        logger.info(
            "Paystack subaccount created: %s for client %s (percentage_charge=%s)",
            subaccount_code, client_id, percentage_charge,
        )
        subaccount = FlutterwaveSubaccount(
            client_id=client_id,
            merchant_id=merchant_id,
            subaccount_id=subaccount_code,
            account_bank=account_bank,
            account_number=account_number,
            business_name=business_name,
            split_value=str(percentage_charge),
            split_type="percentage",
            active=True,
            provider="paystack",
        )
        self.db.add(subaccount)
        await self.db.flush()
        return subaccount

    async def update_percentage_charge(
        self, *, client_id: str, merchant_id: str, percentage_charge: float,
    ) -> FlutterwaveSubaccount:
        """Change an existing store's commission rate. Calls Paystack's
        subaccount update endpoint so it takes effect on the NEXT charge —
        Paystack doesn't retroactively touch settled or in-flight transactions."""
        if not (0 <= percentage_charge <= 100):
            raise ValueError("percentage_charge must be between 0 and 100")

        subaccount = await self.get_for_client(client_id=client_id, merchant_id=merchant_id)
        if not subaccount:
            raise ValueError("No subaccount registered for this store")

        async with httpx.AsyncClient(timeout=20.0) as client:
            res = await client.put(
                f"{PAYSTACK_BASE}/subaccount/{subaccount.subaccount_id}",
                json={"percentage_charge": percentage_charge},
                headers=self._headers(),
            )
        data = res.json()
        if not data.get("status"):
            raise ValueError(f"Paystack subaccount update error: {data.get('message', 'Unknown error')}")

        subaccount.split_value = str(percentage_charge)
        await self.db.flush()
        logger.info(
            "Paystack subaccount %s percentage_charge updated to %s for client %s",
            subaccount.subaccount_id, percentage_charge, client_id,
        )
        return subaccount

    async def get_for_client(
        self, client_id: str, merchant_id: str
    ) -> Optional[FlutterwaveSubaccount]:
        result = await self.db.execute(
            select(FlutterwaveSubaccount).where(
                FlutterwaveSubaccount.client_id == client_id,
                FlutterwaveSubaccount.merchant_id == merchant_id,
                FlutterwaveSubaccount.active.is_(True),
                FlutterwaveSubaccount.provider == "paystack",
            )
        )
        return result.scalar_one_or_none()

    async def get_subaccount_code(
        self, client_id: str, merchant_id: str
    ) -> Optional[str]:
        sub = await self.get_for_client(client_id, merchant_id)
        return sub.subaccount_id if sub else None

    async def deactivate(self, client_id: str, merchant_id: str) -> bool:
        result = await self.db.execute(
            select(FlutterwaveSubaccount).where(
                FlutterwaveSubaccount.client_id == client_id,
                FlutterwaveSubaccount.merchant_id == merchant_id,
                FlutterwaveSubaccount.provider == "paystack",
            )
        )
        subaccount = result.scalar_one_or_none()
        if not subaccount:
            return False
        await self.db.delete(subaccount)
        await self.db.flush()
        return True
