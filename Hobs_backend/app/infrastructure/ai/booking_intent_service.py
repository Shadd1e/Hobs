# app/infrastructure/ai/booking_intent_service.py
#
# Guest-facing intent classification for the hotel booking flow.
# Mirrors deepseek_service.py's _call_llm pattern but with a booking-domain
# schema — kept as a separate function rather than parameterising the shop
# one, since the two intent sets and system prompts genuinely diverge and
# a shared function would need a branch on every call anyway.

import logging
import json
import os
import re
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

ALLOWED_BOOKING_INTENTS = {
    "greeting", "room_inquiry", "check_availability", "book_room",
    "confirm_booking", "provide_guest_name", "cancel_booking",
    "booking_status", "confirm", "cancel", "help", "human_handoff", "other",
}

_FALLBACK_RESULT = {
    "intent": "other",
    "room_type_name": None,
    "check_in": None,
    "check_out": None,
    "guest_name": None,
    "booking_code": None,
    "confidence": 0.0,
}


def _get_deepseek_client():
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY environment variable is not set")
    from openai import AsyncOpenAI
    return AsyncOpenAI(api_key=api_key, base_url="https://api.deepseek.com")


async def classify_booking_intent(
    message: str,
    room_types: Optional[List[dict]] = None,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    current_mode: Optional[str] = None,
    max_retries: int = 2,
) -> Dict[str, Any]:
    """
    room_types is passed in so the LLM can resolve loose/typo'd room type
    names ("the deluxe one", "delux room") against what this specific hotel
    actually offers, rather than guessing from message text alone.
    """
    client = _get_deepseek_client()

    room_type_names = [rt["name"] for rt in (room_types or [])]

    system_prompt = {
        "role": "system",
        "content": (
            "You are an intent classifier for a hotel's WhatsApp booking assistant. "
            f"This hotel's room types are: {', '.join(room_type_names) or '(none configured)'}. "
            "Return ONLY valid JSON with this exact shape:\n"
            "{\n"
            '  "intent": "greeting" | "room_inquiry" | "check_availability" | "book_room" | '
            '"confirm_booking" | "provide_guest_name" | "cancel_booking" | "booking_status" | '
            '"confirm" | "cancel" | "help" | "human_handoff" | "other",\n'
            '  "room_type_name": string | null,  // match against the hotel\'s actual room types above, even if the guest typo\'d it\n'
            '  "check_in": "YYYY-MM-DD" | null,\n'
            '  "check_out": "YYYY-MM-DD" | null,\n'
            '  "guest_name": string | null,\n'
            '  "booking_code": string | null,  // if the guest is asking about an existing booking\n'
            '  "confidence": number (0.0 to 1.0)\n'
            "}\n"
            "Resolve relative dates (e.g. 'this weekend', 'next Friday') against today's date if mentioned in context. "
            "No markdown. No explanation. JSON only."
        ),
    }

    messages = [system_prompt]
    if current_mode:
        messages.append({"role": "system", "content": f"Current conversation mode: {current_mode}"})
    for turn in (conversation_history or [])[-6:]:
        messages.append(turn)
    messages.append({"role": "user", "content": message})

    for attempt in range(max_retries):
        try:
            response = await client.chat.completions.create(
                model="deepseek-chat",
                messages=messages,
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content.strip()
            if raw.startswith("```"):
                m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
                raw = m.group(1).strip() if m else raw.replace("```json", "").replace("```", "").strip()

            result = json.loads(raw)

            if result.get("intent") not in ALLOWED_BOOKING_INTENTS:
                result["intent"] = "other"

            for field, default in _FALLBACK_RESULT.items():
                if field not in result:
                    result[field] = default

            return result

        except json.JSONDecodeError as e:
            logger.warning("Booking intent classifier bad JSON (attempt %d): %s", attempt + 1, e)
            if attempt == max_retries - 1:
                return dict(_FALLBACK_RESULT)

        except Exception as e:
            logger.error("Booking intent classifier error (attempt %d): %s", attempt + 1, e)
            if attempt == max_retries - 1:
                return dict(_FALLBACK_RESULT)
            import asyncio
            await asyncio.sleep(1)

    return dict(_FALLBACK_RESULT)


async def answer_room_question(message: str, hotel_name: str, room_types: List[dict]) -> str:
    """
    For open-ended questions the structured intents don't cover ('does the
    deluxe room have a bathtub?', 'is breakfast included?') — free-text
    answer grounded only in the room_types data actually passed in, so the
    bot can't invent amenities the hotel never listed.
    """
    client = _get_deepseek_client()

    catalogue = "\n".join(
        f"- {rt['name']}: {rt.get('description', 'no description')} — ₦{rt.get('price', 0):,.0f}/night"
        for rt in room_types
    ) or "(no room types configured)"

    system_prompt = {
        "role": "system",
        "content": (
            f"You are a warm, chatty WhatsApp assistant for {hotel_name}. "
            "Answer the guest's question using ONLY the room information below — "
            "never invent amenities, prices, or policies not listed here. "
            "If you don't know, say so and offer to check with staff. "
            "Keep replies short and conversational, WhatsApp style (use *bold* not **bold**), no long paragraphs.\n\n"
            f"Rooms at {hotel_name}:\n{catalogue}"
        ),
    }

    try:
        response = await client.chat.completions.create(
            model="deepseek-chat",
            messages=[system_prompt, {"role": "user", "content": message}],
            temperature=0.4,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error("answer_room_question failed: %s", e)
        return "Sorry, I'm having trouble answering that right now — could you try again in a moment?"
