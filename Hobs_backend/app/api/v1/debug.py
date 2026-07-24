from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete, select

from app.db.session import get_db
from app.models.cart import Cart, CartItem
from app.models.order import Order
from app.core.redis_client import (
    delete_session,
    release_user_lock,
)

# ──────────────────────────────────────────────────────────────────────────────
# AUTH DEPENDENCY
# Enforced at the FastAPI router level so every route in this file requires a
# valid merchant JWT — the handler body no longer has to remember to call
# _require_merchant() manually.
# ──────────────────────────────────────────────────────────────────────────────

def _require_merchant(request: Request) -> str:
    """
    FastAPI dependency: extract merchant_id from JWT-populated request.state.
    Returns the merchant_id string; raises 401 if not authenticated.
    """
    merchant_id = getattr(request.state, "merchant_id", None)
    if not merchant_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    return merchant_id


router = APIRouter(
    prefix="/debug",
    tags=["Debug"],
    dependencies=[Depends(_require_merchant)],
)


@router.post("/user-reset")
async def reset_single_user(
    merchant_id: str,
    user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    # The router-level dependency already verified the token is valid.
    # Enforce that the caller can only reset users within their own account.
    authed_merchant = getattr(request.state, "merchant_id", None)
    if merchant_id != authed_merchant:
        raise HTTPException(status_code=403, detail="Access denied")

    try:
        # ==========================================
        # 1. Clear Redis session state
        # ==========================================

        await delete_session(merchant_id, user_id)

        # Force-release lock (safe reset)
        from app.core.redis_client import redis_service, Keys

        client = await redis_service.get_client()
        await client.delete(Keys.lock(merchant_id, user_id))

        # ==========================================
        # 2. Find active cart
        # ==========================================

        result = await db.execute(
            select(Cart).where(
                Cart.merchant_id == merchant_id,
                Cart.user_id == user_id,
                Cart.checked_out == False,
            )
        )
        cart = result.scalars().first()

        if cart:
            await db.execute(delete(Order).where(Order.cart_id == cart.id))
            await db.execute(delete(CartItem).where(CartItem.cart_id == cart.id))
            await db.execute(delete(Cart).where(Cart.id == cart.id))
            await db.commit()

        return {
            "status": "SUCCESS",
            "message": f"Reset user {user_id}",
        }

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Reset failed: {str(e)}",
        )
