import logging
logger = logging.getLogger(__name__)

from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from sqlalchemy.exc import IntegrityError

from app.domains.product.models import Product
from app.domains.inventory.models import Inventory
from app.schemas.product import ProductCreate


class ProductService:
    """Async CRUD service for Product with tenant-safe auto-inventory."""

    def __init__(self, db: AsyncSession):
        if not db:
            raise ValueError("AsyncSession must be provided")
        self.db = db

    # -----------------------------
    # CREATE
    # -----------------------------
    async def create(self, data: ProductCreate) -> Optional[Product]:
        if not data.merchant_id or not data.client_id:
            return None

        stmt = select(Product).where(
            and_(
                Product.name == data.name,
                Product.merchant_id == data.merchant_id,
                Product.client_id == data.client_id,
            )
        )

        existing = await self.db.execute(stmt)
        if existing.scalars().first():
            return None

        product = Product(
            name=data.name,
            description=data.description,
            category=data.category,
            price=data.price,
            merchant_id=data.merchant_id,
            client_id=data.client_id,
        )

        try:
            self.db.add(product)
            await self.db.flush()

            inventory = Inventory(
                product_id=product.id,
                merchant_id=data.merchant_id,
                client_id=data.client_id,
                quantity=0,
            )
            self.db.add(inventory)

            await self.db.flush()
            return product

        except IntegrityError:
            await self.db.rollback()
            return None

    # -----------------------------
    # READ
    # -----------------------------
    async def get(
        self,
        product_id,
        merchant_id: Optional[str] = None,
        client_id: Optional[str] = None,
    ) -> Optional[Product]:

        stmt = select(Product).where(Product.id == product_id)

        if merchant_id:
            stmt = stmt.where(Product.merchant_id == merchant_id)

        if client_id:
            stmt = stmt.where(Product.client_id == client_id)

        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def list_all(
        self,
        merchant_id: Optional[str] = None,
        client_id: Optional[str] = None,
    ) -> List[Product]:

        stmt = select(Product)

        if merchant_id:
            stmt = stmt.where(Product.merchant_id == merchant_id)

        if client_id:
            stmt = stmt.where(Product.client_id == client_id)

        result = await self.db.execute(stmt)
        return result.scalars().all()

    # -----------------------------
    # UPDATE
    # -----------------------------
    async def update(
        self,
        product_id,
        payload: dict,
        merchant_id: Optional[str] = None,
        client_id: Optional[str] = None,
    ) -> Optional[Product]:

        product = await self.get(product_id, merchant_id, client_id)

        if not product:
            return None

        payload.pop("merchant_id", None)
        payload.pop("client_id", None)

        for key, value in payload.items():
            setattr(product, key, value)

        await self.db.flush()
        return product

    # -----------------------------
    # DELETE
    # -----------------------------
    async def delete(
        self,
        product_id,
        merchant_id: Optional[str] = None,
        client_id: Optional[str] = None,
    ) -> bool:

        product = await self.get(product_id, merchant_id, client_id)

        if not product:
            return False

        await self.db.delete(product)
        await self.db.flush()
        return True