import logging
from typing import List, Optional

from rapidfuzz import fuzz

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func

from app.domains.inventory.models import Inventory
from app.domains.product.models import Product
from app.schemas.fuzzy import FuzzyMatchResultSchema

logger = logging.getLogger(__name__)


class FuzzyMatcher:
    """
    Production fuzzy matcher.

    Pipeline:
    PostgreSQL pg_trgm similarity (hard prefilter)
    → RapidFuzz refinement (final ranking)
    """

    STRONG_MATCH = 80.0
    WEAK_MATCH = 65.0
    MIN_MATCH = 55.0

    SIMILARITY_THRESHOLD = 0.18

    def __init__(self, db: AsyncSession):
        if not db:
            raise ValueError("AsyncSession required")
        self.db = db

    async def search(
        self,
        query: str,
        merchant_id: str,
        client_id: str,
        phone_number_id: Optional[str] = None,
        *,
        limit: int = 5,
    ) -> List[FuzzyMatchResultSchema]:

        if not query:
            return []

        query_str = query.strip().lower()

        filters = [
            Inventory.merchant_id == merchant_id,
            Inventory.client_id == client_id,
            Inventory.quantity > 0,
        ]

        stmt = (
            select(
                Product.id,
                Product.name,
                Product.price,
                Product.description,
                Inventory.quantity,
                func.similarity(func.lower(Product.name), query_str).label("sim"),
            )
            .join(Inventory, Inventory.product_id == Product.id)
            .where(
                and_(
                    *filters,
                    func.similarity(func.lower(Product.name), query_str)
                    > self.SIMILARITY_THRESHOLD,
                )
            )
            .order_by(func.similarity(func.lower(Product.name), query_str).desc())
            .limit(15)
        )

        try:
            result = await self.db.execute(stmt)
            rows = result.all()

        except Exception as e:
            logger.error(f"Postgres fuzzy search failed: {e}")

            stmt_fallback = (
                select(
                    Product.id,
                    Product.name,
                    Product.price,
                    Product.description,
                    Inventory.quantity,
                )
                .join(Inventory, Inventory.product_id == Product.id)
                .where(
                    and_(
                        *filters,
                        Product.name.ilike(f"%{query_str}%"),
                    )
                )
                .limit(15)
            )

            result = await self.db.execute(stmt_fallback)
            rows = result.all()

        if not rows:
            return []

        matches: List[FuzzyMatchResultSchema] = []

        for row in rows:
            product_id = row[0]
            name = row[1]
            price = row[2]
            description = row[3]
            quantity = row[4]

            score = fuzz.token_set_ratio(query_str, name.lower())

            if score >= self.MIN_MATCH:
                matches.append(
                    FuzzyMatchResultSchema(
                        product_id=str(product_id),
                        name=name,
                        score=float(round(score, 2)),
                        price=float(price) if price else None,
                        currency=None,
                        description=description,
                        quantity=quantity,
                    )
                )

        if not matches:
            return []

        matches.sort(key=lambda m: m.score, reverse=True)

        return matches[:limit]

    @staticmethod
    def is_strong_match(match: FuzzyMatchResultSchema) -> bool:
        return match.score >= FuzzyMatcher.STRONG_MATCH

    @staticmethod
    def is_weak_match(match: FuzzyMatchResultSchema) -> bool:
        return FuzzyMatcher.WEAK_MATCH <= match.score < FuzzyMatcher.STRONG_MATCH