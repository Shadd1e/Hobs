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
    ) -> FlutterwaveSubaccount:
        payload = {
            "business_name": business_name,
            "settlement_bank": account_bank,
            "account_number": account_number,
            "percentage_charge": 1.0,
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
        logger.info("Paystack subaccount created: %s for client %s", subaccount_code, client_id)
        subaccount = FlutterwaveSubaccount(
            client_id=client_id,
            merchant_id=merchant_id,
            subaccount_id=subaccount_code,
            account_bank=account_bank,
            account_number=account_number,
            business_name=business_name,
            split_value="1.0",
            split_type="percentage",
            active=True,
        )
        self.db.add(subaccount)
        await self.db.flush()
        return subaccount

    async def get_for_client(
        self, client_id: str, merchant_id: str
    ) -> Optional[FlutterwaveSubaccount]:
        result = await self.db.execute(
            select(FlutterwaveSubaccount).where(
                FlutterwaveSubaccount.client_id == client_id,
                FlutterwaveSubaccount.merchant_id == merchant_id,
                FlutterwaveSubaccount.active.is_(True),
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
            )
        )
        subaccount = result.scalar_one_or_none()
        if not subaccount:
            return False
        await self.db.delete(subaccount)
        await self.db.flush()
        return True
