import logging
logger = logging.getLogger(__name__)

# app/api/v1/products.py
from fastapi import APIRouter, HTTPException, Depends, Query, Request
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.models.product import Product
from app.models.client_model import Client

from app.schemas.product import ProductCreate, ProductRead, ProductUpdate, ProductSearchResult
from app.services.product_service import ProductService
from app.services.fuzzy_match import FuzzyMatcher

from app.db.deps import get_db
from app.core.deps import get_tenant
from app.core.tenant import TenantContext
from app.core.redis_client import rate_limiter

router = APIRouter(prefix="/products", tags=["Products"])


# ---------------------------
# CREATE PRODUCT
# ---------------------------
@router.post("/", response_model=ProductRead)
async def create_product(
    payload: ProductCreate,
    tenant: TenantContext = Depends(get_tenant),
    db: AsyncSession = Depends(get_db),
):
    service = ProductService(db)

    product = await service.create(
        payload.copy(update={
            "merchant_id": tenant.merchant_id,
            "client_id": tenant.client_id,
        })
    )

    if not product:
        raise HTTPException(
            status_code=400,
            detail="Product could not be created. Possible duplicate or invalid data."
        )

    return ProductRead.model_validate(product)


# ---------------------------
# LIST PRODUCTS
# ---------------------------
@router.get("/", response_model=List[ProductRead])
async def list_products(
    tenant: TenantContext = Depends(get_tenant),
    db: AsyncSession = Depends(get_db),
):
    service = ProductService(db)
    return await service.list_all(
        merchant_id=tenant.merchant_id,
        client_id=tenant.client_id,
    )


# ---------------------------
# SEARCH PRODUCTS
# ---------------------------
@router.get("/search", response_model=List[ProductSearchResult],
    dependencies=[Depends(rate_limiter("product-search", max_requests=60, window_seconds=60))])
async def search_products(
    query: str = Query(..., description="Search term for product name"),
    tenant: TenantContext = Depends(get_tenant),
    db: AsyncSession = Depends(get_db),
):
    service = ProductService(db)
    products = await service.list_all(
        merchant_id=tenant.merchant_id,
        client_id=tenant.client_id,
    )

    if not products:
        return []

    matcher = FuzzyMatcher(db)
    items = [{"id": str(p.id), "name": p.name} for p in products]
    matches = await matcher.match(query, items)

    results: List[ProductSearchResult] = []
    for match in matches:
        product_id = getattr(match, "product_id", None)
        score = getattr(match, "score", 0)
        if not product_id:
            continue
        product = next((p for p in products if str(p.id) == product_id), None)
        if product:
            results.append(
                ProductSearchResult(
                    product=ProductRead.model_validate(product),
                    score=score
                )
            )

    results.sort(key=lambda r: r.score, reverse=True)
    return results


# ---------------------------
# ADMIN CREATE (Dashboard)
# ---------------------------
@router.post("/admin/", response_model=ProductRead)
async def create_product_admin(
    payload: ProductCreate,
    request: Request,
    client_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a product from the dashboard. Requires merchant JWT.
    client_id selects which store the product belongs to.
    """
    merchant_id = getattr(request.state, "merchant_id", None)
    if not merchant_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Verify the target store actually belongs to the authenticated merchant.
    # Without this, any merchant could pass another merchant's client_id and
    # create a product tagged with a mismatched merchant_id/client_id pair.
    owner_check = await db.execute(
        select(Client.id).where(
            Client.id == client_id,
            Client.merchant_id == merchant_id,
        )
    )
    if owner_check.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Store not found")

    service = ProductService(db)
    product = await service.create(
        payload.copy(update={"merchant_id": merchant_id, "client_id": client_id})
    )

    if not product:
        raise HTTPException(
            status_code=400,
            detail="Product could not be created. Possible duplicate."
        )

    # Re-query with inventory eagerly loaded so Pydantic can serialize without
    # triggering a lazy async load (which causes MissingGreenlet crash).
    result = await db.execute(
        select(Product)
        .where(Product.id == product.id)
        .options(selectinload(Product.inventory))
    )
    product = result.scalars().first()

    return ProductRead.model_validate(product)


# ---------------------------
# ADMIN UPDATE (Dashboard)
# ---------------------------
@router.patch("/admin/{product_id}", response_model=ProductRead)
async def update_product_admin(
    product_id: str,
    payload: ProductUpdate,
    request: Request,
    client_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Update a product from the dashboard. Requires merchant JWT.
    client_id selects which store the product belongs to.
    """
    merchant_id = getattr(request.state, "merchant_id", None)
    if not merchant_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    service = ProductService(db)

    update_data = payload.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields provided to update")

    product = await service.update(
        product_id=product_id,
        payload=update_data,
        merchant_id=merchant_id,
        client_id=client_id,
    )

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Re-query with inventory eagerly loaded so Pydantic can serialize without
    # triggering a lazy async load (which causes MissingGreenlet crash).
    result = await db.execute(
        select(Product)
        .where(Product.id == product.id)
        .options(selectinload(Product.inventory))
    )
    product = result.scalars().first()

    return ProductRead.model_validate(product)
