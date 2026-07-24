# app/services/fuzzy_match.py

import logging
from typing import List, Optional

from rapidfuzz import fuzz, process

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func

from app.models.inventory import Inventory
from app.models.product import Product
from app.schemas.fuzzy import FuzzyMatchResultSchema

logger = logging.getLogger(__name__)


# ── Pidgin / Nigerian English synonym map ─────────────────────────────────────
# Expands common pidgin terms to standard English before fuzzy matching
# so "pure water" finds "Eva Water", "mineral" finds soft drinks, etc.

_QUERY_SYNONYMS = {
    "pure water":    "water sachet",
    "mineral":       "soft drink",
    "minerals":      "soft drink",
    "pure wata":     "water sachet",
    "coke":          "coca-cola",
    "cokes":         "coca-cola",
    "malt":          "maltina",
    "maggi":         "seasoning cube",
    "indomie":       "noodles",
    "golden morn":   "cereal",
    "tea":           "beverage",
    "garri":         "cassava flakes",
    "eba":           "cassava flakes",
    "cold drink":    "soft drink",
    "soft drink":    "soft drink",
    "zobo":          "hibiscus drink",
    "kunu":          "millet drink",
}


def _normalise_query(query: str) -> str:
    """
    Lowercase, strip punctuation, then apply synonym expansion.
    Returns the normalised string for fuzzy matching.
    """
    import re
    q = re.sub(r"[^\w\s]", " ", query.lower()).strip()
    q = re.sub(r"\s+", " ", q)
    # Check for whole-phrase synonyms first (longest match wins)
    for phrase, replacement in sorted(_QUERY_SYNONYMS.items(), key=lambda x: -len(x[0])):
        if phrase in q:
            q = q.replace(phrase, replacement)
            break
    return q


class FuzzyMatcher:
    """
    Production fuzzy matcher for WhatsApp shopping assistant.

    Pipeline:
      1. Query normalisation + pidgin synonym expansion
      2. PostgreSQL pg_trgm similarity prefilter on name OR description
      3. RapidFuzz blended scoring (name 85% + description 15%)
      4. Variant-group detection for grouped disambiguation

    The description channel lets natural-language clues like "big bottle",
    "chilled drink", "small pack" surface the right product even when the
    product name alone wouldn't match well.
    """

    # RapidFuzz thresholds (0–100)
    STRONG_MATCH = 80.0    # auto-confirm without asking
    WEAK_MATCH   = 65.0    # show in choice list
    MIN_MATCH    = 48.0    # discard below this

    # Blending weights
    NAME_WEIGHT = 0.85
    DESC_WEIGHT = 0.15

    # Postgres pg_trgm threshold (0–1)
    SIMILARITY_THRESHOLD = 0.12  # slightly permissive to let description rescue edge cases

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

        # Normalise + expand synonyms
        query_str = _normalise_query(query)
        # Also keep original lowercase for a secondary pass if needed
        query_original = query.strip().lower()

        filters = [
            Inventory.merchant_id == merchant_id,
            Inventory.client_id   == client_id,
            Inventory.quantity    > 0,
        ]
        if phone_number_id:
            filters.append(Inventory.phone_number_id == phone_number_id)

        # ── Postgres pg_trgm prefilter ────────────────────────────────────────
        name_sim = func.similarity(func.lower(Product.name), query_str)
        desc_sim = func.coalesce(
            func.similarity(func.lower(Product.description), query_str),
            0.0,
        )
        # Also try original query if synonym-expanded version differs
        name_sim_orig = func.similarity(func.lower(Product.name), query_original)

        stmt = (
            select(
                Product.id,
                Product.name,
                Product.price,
                Product.description,
                Product.variant_group,
                Inventory.quantity,
            )
            .join(Inventory, Inventory.product_id == Product.id)
            .where(
                and_(
                    *filters,
                    or_(
                        name_sim      > self.SIMILARITY_THRESHOLD,
                        name_sim_orig > self.SIMILARITY_THRESHOLD,
                        desc_sim      > self.SIMILARITY_THRESHOLD,
                    ),
                )
            )
            .order_by(name_sim.desc())
            .limit(25)
        )

        try:
            result = await self.db.execute(stmt)
            rows   = result.all()
        except Exception as e:
            logger.error("Postgres fuzzy search failed: %s", e)
            await self.db.rollback()
            # ILIKE fallback
            stmt_fallback = (
                select(
                    Product.id,
                    Product.name,
                    Product.price,
                    Product.description,
                    Product.variant_group,
                    Inventory.quantity,
                )
                .join(Inventory, Inventory.product_id == Product.id)
                .where(
                    and_(
                        *filters,
                        or_(
                            Product.name.ilike(f"%{query_str}%"),
                            Product.name.ilike(f"%{query_original}%"),
                        ),
                    )
                )
                .limit(25)
            )
            result = await self.db.execute(stmt_fallback)
            rows   = result.all()

        if not rows:
            return []

        # ── RapidFuzz blended scoring ─────────────────────────────────────────
        matches: List[FuzzyMatchResultSchema] = []

        for row in rows:
            product_id, name, price, description, variant_group, quantity = row

            # Score against both the normalised and original query; take the higher
            name_score_norm = fuzz.token_set_ratio(query_str, name.lower())
            name_score_orig = fuzz.token_set_ratio(query_original, name.lower())
            name_score      = max(name_score_norm, name_score_orig)

            desc_score = 0.0
            if description:
                desc_score = max(
                    fuzz.partial_ratio(query_str,     description.lower()),
                    fuzz.partial_ratio(query_original, description.lower()),
                )

            blended = min(100.0, (name_score * self.NAME_WEIGHT) + (desc_score * self.DESC_WEIGHT))

            if blended >= self.MIN_MATCH:
                m = FuzzyMatchResultSchema(
                    product_id=str(product_id),
                    name=name,
                    score=float(round(blended, 2)),
                    price=float(price) if price else None,
                    currency=None,
                    description=description,
                    quantity=quantity,
                )
                m.__dict__["variant_group"] = variant_group
                matches.append(m)

        if not matches:
            return []

        matches.sort(key=lambda m: m.score, reverse=True)
        return matches[:limit]

    # ── Variant group detection ───────────────────────────────────────────────

    @staticmethod
    def detect_variant_group(
        matches: List[FuzzyMatchResultSchema],
        query: str,
    ) -> Optional[str]:
        """
        Returns the variant_group name if the top matches all belong to the
        same group AND the query looks like it refers to the group rather than
        a specific variant.
        """
        if len(matches) < 2:
            return None

        groups = {
            getattr(m, "__dict__", {}).get("variant_group") or ""
            for m in matches
        }
        if len(groups) != 1:
            return None
        group = groups.pop()
        if not group:
            return None

        q = _normalise_query(query)
        group_score     = fuzz.token_set_ratio(q, group.lower())
        best_name_score = max(fuzz.token_set_ratio(q, m.name.lower()) for m in matches)

        # Group query when query matches the group name well and individual
        # product names don't score substantially better
        if group_score >= 60 and group_score >= best_name_score - 15:
            return group

        return None

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def is_strong_match(match: FuzzyMatchResultSchema) -> bool:
        return match.score >= FuzzyMatcher.STRONG_MATCH

    @staticmethod
    def is_weak_match(match: FuzzyMatchResultSchema) -> bool:
        return FuzzyMatcher.WEAK_MATCH <= match.score < FuzzyMatcher.STRONG_MATCH
