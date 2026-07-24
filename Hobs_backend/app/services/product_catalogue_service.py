# app/services/product_catalogue_service.py
"""
ProductCatalogueService

Fetches the full product catalogue for a store and formats it as a compact
string ready for injection into the AI system prompt.

Design goals:
  - Redis-cached per (merchant_id, client_id) with a 10-minute TTL
  - Cache invalidated when products are created/updated (call invalidate())
  - Returns a compact, token-efficient string — not full JSON
  - Never raises — returns empty string on any failure so the AI still works

Format injected into prompt:
  Coca-Cola 50cl | ₦500 | drinks | in stock
  Pepsi 50cl | ₦450 | drinks | in stock
  Indomie Chicken | ₦250 | noodles [variant] | in stock
  Eva Water 75cl | ₦200 | water [variant] | out of stock

Variant group is tagged [variant] so the AI knows to offer a list when the
group name is requested (e.g. "noodles" → show all noodle variants).
Cross-sells: because the AI sees the full catalogue, it naturally suggests
alternatives when a requested item is absent.
"""

import logging
import os
from typing import Optional

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.product import Product
from app.models.inventory import Inventory

logger = logging.getLogger(__name__)

REDIS_URL       = os.getenv("REDIS_URL")
CATALOGUE_TTL   = 10 * 60          # 10 minutes
CURRENCY_SYMBOL = os.getenv("CURRENCY_SYMBOL", "₦")

# Max products to include — keeps token budget sane for very large catalogues
MAX_CATALOGUE_PRODUCTS = 200


def _cache_key(merchant_id: str, client_id: str) -> str:
    return f"catalogue:{merchant_id}:{client_id}"


class ProductCatalogueService:

    def __init__(self):
        if REDIS_URL:
            self.redis = aioredis.from_url(REDIS_URL, decode_responses=True)
        else:
            self.redis = None
            logger.warning("REDIS_URL not set — catalogue caching disabled")

    # ── Public API ─────────────────────────────────────────────────────────────

    async def get_catalogue_context(
        self,
        *,
        db: AsyncSession,
        merchant_id: str,
        client_id: str,
    ) -> str:
        """
        Return a formatted catalogue string for AI system prompt injection.
        Checks Redis cache first; falls back to DB and re-populates the cache.
        Returns empty string on any failure — AI degrades gracefully.
        """
        try:
            cached = await self._get_cached(merchant_id, client_id)
            if cached:
                return cached

            fresh = await self._build_from_db(db, merchant_id, client_id)
            if fresh:
                await self._set_cached(merchant_id, client_id, fresh)
            return fresh

        except Exception:
            logger.exception(
                "get_catalogue_context failed for %s/%s", merchant_id, client_id
            )
            return ""

    async def invalidate(self, merchant_id: str, client_id: str) -> None:
        """
        Call this after any product create/update/delete so the next request
        fetches fresh data from the DB.
        """
        if not self.redis:
            return
        try:
            await self.redis.delete(_cache_key(merchant_id, client_id))
            logger.debug(
                "Catalogue cache invalidated for %s/%s", merchant_id, client_id
            )
        except Exception:
            logger.exception("Catalogue cache invalidation failed")

    # ── Internals ──────────────────────────────────────────────────────────────

    async def _get_cached(
        self, merchant_id: str, client_id: str
    ) -> Optional[str]:
        if not self.redis:
            return None
        try:
            return await self.redis.get(_cache_key(merchant_id, client_id))
        except Exception:
            logger.exception("Catalogue cache read failed")
            return None

    async def _set_cached(
        self, merchant_id: str, client_id: str, value: str
    ) -> None:
        if not self.redis:
            return
        try:
            await self.redis.setex(
                _cache_key(merchant_id, client_id),
                CATALOGUE_TTL,
                value,
            )
        except Exception:
            logger.exception("Catalogue cache write failed")

    async def _build_from_db(
        self,
        db: AsyncSession,
        merchant_id: str,
        client_id: str,
    ) -> str:
        """
        Query the DB for all products (with inventory) and format into
        a compact catalogue string.
        """
        result = await db.execute(
            select(Product)
            .where(
                Product.merchant_id == merchant_id,
                Product.client_id   == client_id,
            )
            .options(selectinload(Product.inventory))
            .order_by(Product.category.asc().nullslast(), Product.name.asc())
            .limit(MAX_CATALOGUE_PRODUCTS)
        )
        products = result.scalars().all()

        if not products:
            return ""

        lines = []
        for p in products:
            # Availability — skip out-of-stock products entirely so the AI
            # never recommends items the customer can't actually buy.
            inv = p.inventory
            qty = inv.quantity if inv else 0
            if qty <= 0:
                continue

            stock_tag = "in stock"

            # Category / variant
            if p.variant_group:
                cat_tag = f"{p.variant_group} [variant]"
            elif p.category:
                cat_tag = p.category.lower()
            else:
                cat_tag = "general"

            # Price
            if p.price is not None:
                price_tag = f"{CURRENCY_SYMBOL}{p.price:,.0f}"
            else:
                price_tag = "price on request"

            lines.append(
                f"{p.name} | {price_tag} | {cat_tag} | {stock_tag}"
            )

        return "\n".join(lines)
