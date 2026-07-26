# app/infrastructure/ai/staff_intent_service.py
#
# Extracts structured booking actions from staff WhatsApp messages, e.g.
# "rum 4 boked 3 nyt", "checkout room 12", "room 6 don empty". This is the
# core of the "even with strong spelling, the system is very intelligent"
# requirement — LLM handles typo tolerance + pidgin interpretation, then
# RoomMatcher (app/services/room_matcher.py) validates the extracted room
# number against the hotel's real rooms as a safety net in case the LLM
# hallucinates a room that doesn't exist.

import logging
import json
import os
import re
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

ALLOWED_STAFF_ACTIONS = {
    "book",         # room now occupied by a new guest
    "check_in",     # guest with an existing PAID booking has physically arrived
    "check_out",    # guest has left, room is free again
    "cancel",       # booking should be cancelled
    "status_query", # staff asking "which rooms are free" rather than reporting an update
    "unclear",
}

# Pidgin / shorthand phrases staff commonly use — given directly to the LLM
# as interpretation hints, same spirit as fuzzy_match.py's _QUERY_SYNONYMS
# but for actions rather than product names (a fixed synonym dict doesn't
# work as well here since staff phrasing varies more in structure, not
# just vocabulary — so this feeds the prompt rather than doing pre-match
# substitution).
_ACTION_HINTS = {
    "don leave": "check_out",
    "don comot": "check_out",
    "don empty": "check_out",
    "e don empty": "check_out",
    "checkout": "check_out",
    "check out": "check_out",
    "don enter": "check_in",
    "don arrive": "check_in",
    "check in": "check_in",
    "checkin": "check_in",
    "booked": "book",
    "boked": "book",
    "taken": "book",
    "occupied": "book",
    "cancel": "cancel",
    "wetin free": "status_query",
    "which room free": "status_query",
    "free rooms": "status_query",
}

_FALLBACK_RESULT = {
    "action": "unclear",
    "room_number": None,
    "room_type_name": None,
    "guest_name": None,
    "nights": None,
    "confidence": 0.0,
}


def _get_deepseek_client():
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY environment variable is not set")
    from openai import AsyncOpenAI
    return AsyncOpenAI(api_key=api_key, base_url="https://api.deepseek.com")


async def classify_staff_message(
    message: str,
    real_room_numbers: Optional[List[str]] = None,
    max_retries: int = 2,
) -> Dict[str, Any]:
    client = _get_deepseek_client()

    hints_str = "; ".join(f'"{k}" means {v}' for k, v in _ACTION_HINTS.items())
    rooms_str = ", ".join(real_room_numbers or []) or "(not provided)"

    system_prompt = {
        "role": "system",
        "content": (
            "You extract a structured booking action from a hotel staff member's "
            "WhatsApp message. Staff often type quickly with typos, abbreviations, "
            "and Nigerian Pidgin English — interpret intent, don't require exact spelling.\n\n"
            f"Common shorthand: {hints_str}.\n"
            f"This hotel's real room numbers are: {rooms_str}. Extract the room number "
            "exactly as the staff member wrote it (even if misspelled/malformed) — do NOT "
            "correct it yourself, a separate matching step handles that.\n\n"
            "Return ONLY valid JSON with this exact shape:\n"
            "{\n"
            '  "action": "book" | "check_in" | "check_out" | "cancel" | "status_query" | "unclear",\n'
            '  "room_number": string | null,  // as staff typed it, e.g. "4", "rum4", "12b"\n'
            '  "room_type_name": string | null,\n'
            '  "guest_name": string | null,\n'
            '  "nights": number | null,\n'
            '  "confidence": number (0.0 to 1.0)\n'
            "}\n"
            "No markdown. No explanation. JSON only."
        ),
    }

    for attempt in range(max_retries):
        try:
            response = await client.chat.completions.create(
                model="deepseek-chat",
                messages=[system_prompt, {"role": "user", "content": message}],
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content.strip()
            if raw.startswith("```"):
                m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
                raw = m.group(1).strip() if m else raw.replace("```json", "").replace("```", "").strip()

            result = json.loads(raw)

            if result.get("action") not in ALLOWED_STAFF_ACTIONS:
                result["action"] = "unclear"

            for field, default in _FALLBACK_RESULT.items():
                if field not in result:
                    result[field] = default

            return result

        except json.JSONDecodeError as e:
            logger.warning("Staff intent classifier bad JSON (attempt %d): %s", attempt + 1, e)
            if attempt == max_retries - 1:
                return dict(_FALLBACK_RESULT)

        except Exception as e:
            logger.error("Staff intent classifier error (attempt %d): %s", attempt + 1, e)
            if attempt == max_retries - 1:
                return dict(_FALLBACK_RESULT)
            import asyncio
            await asyncio.sleep(1)

    return dict(_FALLBACK_RESULT)
