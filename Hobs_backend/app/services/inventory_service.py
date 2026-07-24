# app/services/inventory_service.py

import logging
from typing import Optional, List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import SQLAlchemyError

from app.models.inventory import Inventory
from app.models.product import Product
from app.schemas.product import ProductRead

logger = logging.getLogger(__name__)


class InventoryService:
    """
    Inventory domain service.

    RULES:
    - Inventory quantity is the single source of truth
    - Inventory is modified ONLY during checkout / fulfillment
    - No reservations
    - No commits or rollbacks (caller owns transaction)
    """

    def __init__(self, db: AsyncSession):
        if not db:
            raise ValueError("AsyncSession must be provided")
        self.db = db

    # =====================================================
    # READ-ONLY: LIST PRODUCTS WITH INVENTORY (TENANT SAFE)
    # =====================================================
    async def list_products_for_client(
        self,
        merchant_id: str,
        client_id: Optional[str] = None,
    ) -> List[ProductRead]:
        stmt = (
            select(Product)
            .join(Inventory, Inventory.product_id == Product.id)
            .where(
                Inventory.merchant_id == merchant_id,
                Product.merchant_id == merchant_id,
            )
            .options(selectinload(Product.inventory))
        )

        if client_id:
            stmt = stmt.where(
                Inventory.client_id == client_id,
                Product.client_id == client_id,
            )

        result = await self.db.execute(stmt)
        products = result.scalars().unique().all()

        return [ProductRead.model_validate(p) for p in products]

    # =====================================================
    # READ: GET INVENTORY ROW (TENANT SAFE)
    # =====================================================
    async def get_inventory(
        self,
        merchant_id: str,
        client_id: str,
        product_id: str,
    ) -> Optional[Inventory]:
        result = await self.db.execute(
            select(Inventory).where(
                Inventory.merchant_id == merchant_id,
                Inventory.client_id == client_id,
                Inventory.product_id == product_id,
            )
        )
        return result.scalars().first()

    # =====================================================
    # INTERNAL: GET OR CREATE INVENTORY ROW
    # =====================================================
    async def get_or_create_inventory(
        self,
        merchant_id: str,
        client_id: str,
        product_id: str,
        quantity: int = 0,
    ) -> Inventory:
        inventory = await self.get_inventory(
            merchant_id=merchant_id,
            client_id=client_id,
            product_id=product_id,
        )

        if inventory:
            return inventory

        inventory = Inventory(
            merchant_id=merchant_id,
            client_id=client_id,
            product_id=product_id,
            quantity=max(quantity, 0),
        )

        self.db.add(inventory)

        logger.info(
            "Inventory row created",
            extra={
                "merchant_id": merchant_id,
                "client_id": client_id,
                "product_id": product_id,
                "quantity": inventory.quantity,
            },
        )

        return inventory

    # =====================================================
    # ADMIN: ADJUST STOCK (LOCKED)
    # =====================================================
    async def adjust_stock(
        self,
        merchant_id: str,
        client_id: str,
        product_id: str,
        delta: int,
    ) -> Inventory:
        result = await self.db.execute(
            select(Inventory)
            .where(
                Inventory.merchant_id == merchant_id,
                Inventory.client_id == client_id,
                Inventory.product_id == product_id,
            )
            .with_for_update()
        )
        inventory = result.scalars().first()

        if not inventory:
            raise ValueError("Inventory record not found")

        new_quantity = inventory.quantity + delta
        if new_quantity < 0:
            raise ValueError("Stock cannot go below zero")

        inventory.quantity = new_quantity

        logger.info(
            "Inventory adjusted",
            extra={
                "product_id": product_id,
                "delta": delta,
                "new_quantity": new_quantity,
            },
        )

        return inventory

    # =====================================================
    # READ: CHECK AVAILABILITY (NON-FINAL)
    # =====================================================
    async def ensure_available(
        self,
        merchant_id: str,
        client_id: str,
        product_id: str,
        requested_qty: int,
    ) -> None:
        inventory = await self.get_inventory(
            merchant_id=merchant_id,
            client_id=client_id,
            product_id=product_id,
        )

        if not inventory:
            raise ValueError("Inventory record not found")

        if inventory.quantity < requested_qty:
            raise ValueError("Insufficient stock")

    # =====================================================
    # WRITE: FINALIZE SALE (LOCKED, FINAL)
    # =====================================================
    async def finalize_sale(
        self,
        merchant_id: str,
        client_id: str,
        product_id: str,
        quantity: int,
    ) -> Inventory:
        """
        Deduct inventory during checkout or fulfillment.

        - Must be called inside an active transaction
        - Locks inventory row
        - Final authority on stock deduction
        """

        if quantity <= 0:
            raise ValueError("Finalize quantity must be positive")

        result = await self.db.execute(
            select(Inventory)
            .where(
                Inventory.merchant_id == merchant_id,
                Inventory.client_id == client_id,
                Inventory.product_id == product_id,
            )
            .with_for_update()
        )
        inventory = result.scalars().first()

        if not inventory:
            raise ValueError("Inventory record not found")

        if inventory.quantity < quantity:
            raise ValueError("Insufficient inventory")

        inventory.quantity -= quantity

        logger.info(
            "Inventory finalized",
            extra={
                "product_id": product_id,
                "quantity_deducted": quantity,
                "remaining": inventory.quantity,
            },
        )

        # Flag low stock / out of stock for post-transaction notification
        inventory._low_stock_remaining = inventory.quantity
        inventory._low_stock_triggered = (
            inventory.low_stock_threshold is not None
            and inventory.quantity <= inventory.low_stock_threshold
        )

        # FIX: invalidate the catalogue cache when stock hits zero so the AI
        # stops recommending this product immediately rather than waiting up to
        # 10 minutes for the TTL to expire. Fire-and-forget — a cache miss is
        # handled gracefully by get_catalogue_context() so failure is non-fatal.
        if inventory.quantity <= 0:
            try:
                from app.services.product_catalogue_service import ProductCatalogueService
                _cat = ProductCatalogueService()
                import asyncio as _asyncio
                _asyncio.create_task(
                    _cat.invalidate(merchant_id=merchant_id, client_id=client_id)
                )
            except Exception as _inv_err:
                logger.warning(
                    "Catalogue invalidation after stock-out failed (non-fatal): %s",
                    _inv_err,
                )

        return inventory