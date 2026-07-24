from fastapi import APIRouter, Depends, Request, HTTPException, Query
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.product import ProductRead
from app.services.inventory_service import InventoryService
import logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/inventory", tags=["Inventory"])


def _require_merchant(request: Request) -> str:
    """JWT guard — rejects unauthenticated requests with 401."""
    merchant_id = getattr(request.state, "merchant_id", None)
    if not merchant_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    return merchant_id


@router.get("/", response_model=List[ProductRead], response_model_exclude_none=True)
async def list_inventory(
    request: Request,
    client_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Return all products accessible to the client under the given merchant.
    Essentially a view of the inventory scoped by tenant.
    """
    merchant_id = _require_merchant(request)
    service = InventoryService(db)
    products = await service.list_products_for_client(merchant_id, client_id)
    return products

@router.patch("/{product_id}/low-stock-threshold")
async def set_low_stock_threshold(
    product_id: str,
    request: Request,
    client_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Set the low stock warning threshold for a product.
    Operator is notified when stock drops to or below this number.

    Body: {"threshold": 5}
    Set threshold to null to disable warnings for this product.
    """
    merchant_id = _require_merchant(request)

    body = await request.json()
    threshold = body.get("threshold")  # int or None

    if threshold is not None and (not isinstance(threshold, int) or threshold < 0):
        raise HTTPException(status_code=400, detail="threshold must be a non-negative integer or null")

    from sqlalchemy import select
    from app.models.inventory import Inventory
    result = await db.execute(
        select(Inventory).where(
            Inventory.merchant_id == merchant_id,
            Inventory.client_id == client_id,
            Inventory.product_id == product_id,
        )
    )
    inv = result.scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="Inventory record not found for this product")

    inv.low_stock_threshold = threshold
    await db.commit()

    return {
        "detail": "Low stock threshold updated",
        "product_id": product_id,
        "low_stock_threshold": threshold,
        "current_quantity": inv.quantity,
    }


@router.post("/{product_id}/adjust")
async def adjust_stock(
    product_id: str,
    request: Request,
    client_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Adjust stock by a delta (positive = add, negative = remove).
    Or set absolute quantity via set_to field.
    Body: {"delta": 10} or {"set_to": 50}
    """
    merchant_id = _require_merchant(request)

    body = await request.json()
    delta = body.get("delta")
    set_to = body.get("set_to")

    from sqlalchemy import select
    from app.models.inventory import Inventory

    result = await db.execute(
        select(Inventory).where(
            Inventory.merchant_id == merchant_id,
            Inventory.client_id == client_id,
            Inventory.product_id == product_id,
        ).with_for_update()
    )
    inv = result.scalar_one_or_none()

    if not inv:
        # Create inventory record if it doesn't exist
        inv = Inventory(
            merchant_id=merchant_id,
            client_id=client_id,
            product_id=product_id,
            quantity=0,
        )
        db.add(inv)

    if set_to is not None:
        if not isinstance(set_to, int) or set_to < 0:
            raise HTTPException(status_code=400, detail="set_to must be a non-negative integer")
        inv.quantity = set_to
    elif delta is not None:
        new_qty = inv.quantity + int(delta)
        if new_qty < 0:
            raise HTTPException(status_code=400, detail="Stock cannot go below zero")
        inv.quantity = new_qty
    else:
        raise HTTPException(status_code=400, detail="Provide either delta or set_to")

    await db.commit()

    return {
        "detail": "Stock adjusted",
        "product_id": product_id,
        "quantity": inv.quantity,
    }
