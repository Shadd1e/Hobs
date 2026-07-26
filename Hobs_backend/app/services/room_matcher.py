# app/services/room_matcher.py
#
# Deliberately NOT a reuse of app/services/fuzzy_match.py's FuzzyMatcher —
# that class is hard-wired to a Postgres pg_trgm query against Product/
# Inventory and is built for matching longer product names/descriptions.
# Room numbers and room-type names are short tokens ("4", "12B", "Deluxe")
# where trigram similarity is unreliable (trigrams need ~3+ chars to mean
# anything), so a straightforward in-memory RapidFuzz comparison against
# the hotel's actual room list is both simpler and more accurate here.

import logging
from typing import List, Optional
from rapidfuzz import fuzz, process

logger = logging.getLogger(__name__)


class RoomMatcher:
    """
    Matches a staff-typed room identifier ("rum 4", "room4", "12 b") against
    a hotel's real room numbers, and separately can match loose room-type
    names against real room type names. Two independent static methods
    rather than a stateful class, since callers already have the candidate
    list loaded (from RoomService) and there's no DB query to encapsulate.
    """

    STRONG_MATCH = 80.0
    MIN_MATCH = 55.0  # room numbers are short, so this floor is lower than
                       # the product matcher's 48 — a couple of matching
                       # chars out of "4" or "12B" is proportionally more
                       # significant than for a full product name.

    @staticmethod
    def _clean_token(text: str) -> str:
        """Strip common staff filler words ('room', 'rm', '#') before comparing."""
        text = text.strip().lower()
        for prefix in ("room ", "rm ", "rm", "room", "#", "no.", "no "):
            if text.startswith(prefix):
                text = text[len(prefix):].strip()
        return text

    @classmethod
    def match_room_number(cls, typed: str, real_room_numbers: List[str]) -> Optional[str]:
        """
        Returns the best-matching real room_number, or None if nothing
        clears MIN_MATCH. Tries an exact/cleaned match first (the common
        case — staff usually get the digits right even with typos
        elsewhere), then falls back to RapidFuzz.
        """
        if not typed or not real_room_numbers:
            return None

        cleaned = cls._clean_token(typed)

        # Exact match on the cleaned token — covers the vast majority of
        # real staff messages ("room 4" -> "4").
        for real in real_room_numbers:
            if cleaned == real.strip().lower():
                return real

        result = process.extractOne(
            cleaned,
            real_room_numbers,
            scorer=fuzz.ratio,
            score_cutoff=cls.MIN_MATCH,
        )
        if result:
            matched_value, score, _ = result
            logger.info("Room number fuzzy match: %r -> %r (score %.1f)", typed, matched_value, score)
            return matched_value
        return None

    @classmethod
    def match_room_type(cls, typed: str, real_room_type_names: List[str]) -> Optional[str]:
        if not typed or not real_room_type_names:
            return None
        cleaned = typed.strip().lower()
        for real in real_room_type_names:
            if cleaned == real.strip().lower():
                return real
        result = process.extractOne(
            cleaned,
            real_room_type_names,
            scorer=fuzz.WRatio,
            score_cutoff=cls.MIN_MATCH,
        )
        return result[0] if result else None
