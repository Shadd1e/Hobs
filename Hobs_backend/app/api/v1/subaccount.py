# app/api/v1/subaccount.py
import logging
from fastapi import APIRouter, Depends, HTTPException, Request

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.flutterwave_subaccount import SubaccountRegisterRequest, SubaccountRead
from app.services.flutterwave_subaccount_service import FlutterwaveSubaccountService
from app.db.deps import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/subaccounts", tags=["Subaccounts"])


def _require_merchant(request: Request) -> str:
    merchant_id = getattr(request.state, "merchant_id", None)
    if not merchant_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    return merchant_id


@router.get("/banks")
async def list_banks(request: Request, db: AsyncSession = Depends(get_db)):
    """Returns all Nigerian banks supported by Flutterwave."""
    _require_merchant(request)
    try:
        service = FlutterwaveSubaccountService(db)
        banks = await service.list_banks()
        return {"banks": banks}
    except ValueError as e:
        logger.warning("list_banks error: %s", e)
        raise HTTPException(status_code=502, detail="Unable to retrieve bank list. Please try again.")


@router.post("/verify-account")
async def verify_bank_account(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Verify a bank account number against Flutterwave."""
    merchant_id = _require_merchant(request)

    from app.core.redis_client import check_rate_limit
    if not await check_rate_limit(f"bank-verify:{merchant_id}", max_requests=10, window_seconds=600):
        raise HTTPException(
            status_code=429,
            detail="Too many verification attempts. Please wait a few minutes and try again.",
        )

    body = await request.json()
    account_number = body.get("account_number", "").strip()
    bank_code = body.get("account_bank", "").strip()
    if not account_number or not bank_code:
        raise HTTPException(status_code=400, detail="account_number and account_bank required")
    try:
        service = FlutterwaveSubaccountService(db)
        result = await service.verify_account(account_number, bank_code)
        return result
    except ValueError as e:
        logger.warning("verify_bank_account error: %s", e)
        raise HTTPException(status_code=400, detail="Unable to verify account. Please try again.")


@router.post("/{client_id}", response_model=SubaccountRead, status_code=201)
async def register_subaccount(
    client_id: str,
    payload: SubaccountRegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Register a Flutterwave subaccount for a store (client).

    Calls Flutterwave's API with the store's bank details and saves the returned
    subaccount_code. Once registered, all card payments from that store will
    route directly to this bank account.
    """
    merchant_id = _require_merchant(request)

    service = FlutterwaveSubaccountService(db)

    existing = await service.get_for_client(
        client_id=client_id,
        merchant_id=merchant_id,
    )
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Subaccount already registered for this store: {existing.subaccount_id}"
        )

    # percentage_charge is deliberately NOT taken from the merchant's own
    # request here — a store owner shouldn't be able to set their own
    # platform commission. Self-serve registration always uses the platform
    # default; an admin can set a custom per-store rate afterward via
    # POST /admin/whatsapp-setup/merchants/{merchant_id}/clients/{client_id}/commission.
    try:
        subaccount = await service.register(
            client_id=client_id,
            merchant_id=merchant_id,
            account_bank=payload.account_bank,
            account_number=payload.account_number,
            account_name=payload.account_name,
            business_name=payload.business_name,
        )
        return subaccount
    except ValueError as e:
        logger.warning("register_subaccount ValueError: %s", e)
        raise HTTPException(status_code=400, detail="Unable to process request. Please try again.")
    except Exception:
        logger.exception("Subaccount registration failed for client %s", client_id)
        raise HTTPException(status_code=500, detail="Subaccount registration failed")


@router.get("/{client_id}", response_model=SubaccountRead)
async def get_subaccount(
    client_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Get the registered subaccount for a store."""
    merchant_id = _require_merchant(request)

    service = FlutterwaveSubaccountService(db)
    subaccount = await service.get_for_client(
        client_id=client_id,
        merchant_id=merchant_id,
    )
    if not subaccount:
        raise HTTPException(status_code=404, detail="No subaccount registered for this store")
    return subaccount


@router.delete("/{client_id}")
async def deactivate_subaccount(
    client_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Deactivate a store's subaccount. Payments will fall back to platform account."""
    merchant_id = _require_merchant(request)

    service = FlutterwaveSubaccountService(db)
    success = await service.deactivate(
        client_id=client_id,
        merchant_id=merchant_id,
    )
    if not success:
        raise HTTPException(status_code=404, detail="No subaccount found")
    return {"detail": "Subaccount deactivated"}
