# app/api/v1/cart.py

import logging
from fastapi import APIRouter, HTTPException, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.deps import get_db
from app.schemas.cart import (
    CartSchema,
    CartItemSchema,
    CartAddItem,
    CartRemoveItem,
)
from app.services.cart_service import CartService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cart", tags=["Cart"])


def _require_merchant(request: Request) -> str:
    merchant_id = getattr(request.state, "merchant_id", None)
    if not merchant_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    return merchant_id


# -------------------------------------------------
# ADD ITEM
# -------------------------------------------------

@router.post("/add-item", response_model=CartSchema, status_code=status.HTTP_200_OK)
async def add_item_by_merchant_user(
    item: CartAddItem,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    authed_id = _require_merchant(request)
    if item.merchant_id != authed_id:
        raise HTTPException(status_code=403, detail="Access denied")
    service = CartService(db)

    try:
        cart = await service.get_active_cart(
            merchant_id=item.merchant_id,
            client_id=item.client_id,
            user_id=item.user_id,
        )

        if not cart:
            cart = await service.create_cart(
                merchant_id=item.merchant_id,
                client_id=item.client_id,
                user_id=item.user_id,
            )

        return await service.add_item(
            merchant_id=item.merchant_id,
            client_id=item.client_id,
            cart_id=cart.id,
            item=CartItemSchema(
                product_id=item.product_id,
                quantity=item.quantity,
                price_at_add=item.price_at_add,
            ),
        )

    except ValueError as e:
        logger.warning("Add item failed: %s", str(e))
        raise HTTPException(status_code=400, detail="Unable to process request. Please try again.")


# -------------------------------------------------
# REMOVE ITEM
# -------------------------------------------------

@router.post("/remove-item", response_model=CartSchema, status_code=status.HTTP_200_OK)
async def remove_item_by_merchant_user(
    item: CartRemoveItem,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    authed_id = _require_merchant(request)
    if item.merchant_id != authed_id:
        raise HTTPException(status_code=403, detail="Access denied")
    service = CartService(db)

    cart = await service.get_active_cart(
        merchant_id=item.merchant_id,
        client_id=item.client_id,
        user_id=item.user_id,
    )

    if not cart:
        raise HTTPException(status_code=404, detail="Cart not found")

    try:
        return await service.remove_item(
            merchant_id=item.merchant_id,
            client_id=item.client_id,
            cart_id=cart.id,
            product_id=item.product_id,
        )
    except ValueError as e:
        logger.warning("Remove item failed: %s", str(e))
        raise HTTPException(status_code=400, detail="Unable to process request. Please try again.")


# -------------------------------------------------
# VIEW ACTIVE CART
# -------------------------------------------------

@router.get("/view", response_model=CartSchema)
async def view_cart_by_merchant_user(
    merchant_id: str,
    client_id: str,
    user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    authed_id = _require_merchant(request)
    if merchant_id != authed_id:
        raise HTTPException(status_code=403, detail="Access denied")
    service = CartService(db)

    cart = await service.get_active_cart(
        merchant_id=merchant_id,
        client_id=client_id,
        user_id=user_id,
    )

    if not cart:
        raise HTTPException(status_code=404, detail="Cart not found")

    return cart


# -------------------------------------------------
# CREATE CART
# -------------------------------------------------

@router.post("/create", response_model=CartSchema)
async def create_cart(
    merchant_id: str,
    client_id: str,
    user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    authed_id = _require_merchant(request)
    if merchant_id != authed_id:
        raise HTTPException(status_code=403, detail="Access denied")
    service = CartService(db)

    return await service.create_cart(
        merchant_id=merchant_id,
        client_id=client_id,
        user_id=user_id,
    )


# -------------------------------------------------
# GET CART BY ID (TENANT SAFE)
# -------------------------------------------------

@router.get("/{cart_id}", response_model=CartSchema)
async def get_cart(
    cart_id: str,
    merchant_id: str,
    client_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    authed_id = _require_merchant(request)
    if merchant_id != authed_id:
        raise HTTPException(status_code=403, detail="Access denied")
    service = CartService(db)

    cart = await service.get_cart(
        merchant_id=merchant_id,
        client_id=client_id,
        cart_id=cart_id,
    )

    if not cart:
        raise HTTPException(status_code=404, detail="Cart not found")

    return cart


# -------------------------------------------------
# CLEAR CART
# -------------------------------------------------

@router.delete("/{cart_id}", status_code=status.HTTP_200_OK)
async def clear_cart(
    cart_id: str,
    merchant_id: str,
    client_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    authed_id = _require_merchant(request)
    if merchant_id != authed_id:
        raise HTTPException(status_code=403, detail="Access denied")
    service = CartService(db)

    try:
        await service.clear_cart(
            merchant_id=merchant_id,
            client_id=client_id,
            cart_id=cart_id,
        )
        return {"message": "Cart cleared"}
    except ValueError as e:
        logger.warning("Clear cart failed: %s", str(e))
        raise HTTPException(status_code=400, detail="Unable to process request. Please try again.")