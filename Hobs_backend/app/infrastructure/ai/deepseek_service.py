# app/infrastructure/ai/deepseek_service.py
import logging
import json
import os
import re
from typing import Dict, Any, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

CURRENCY_SYMBOL = os.getenv("CURRENCY_SYMBOL", "₦")

ALLOWED_INTENTS = {
    "greeting", "product_search", "add_to_cart", "view_cart",
    "remove_from_cart", "update_quantity", "clear_cart", "checkout",
    "info", "help", "confirm", "cancel", "select_by_number", "other",
}

INTENT_KEYWORDS = {
    "greeting": ["hi", "hello", "hey", "good morning", "good afternoon", "good evening"],
    "product_search": ["looking for", "find", "search", "got any", "do you have", "available"],
    "add_to_cart": ["add", "buy", "get", "order", "i want", "i'll take", "put in cart"],
    "view_cart": ["show cart", "view cart", "what's in my cart", "my cart"],
    "remove_from_cart": ["remove", "delete", "take out", "don't want"],
    "update_quantity": ["change", "update", "want", "need", "make it", "set to"],
    "clear_cart": ["clear cart", "empty cart", "remove all"],
    "checkout": ["checkout", "pay", "order now", "complete purchase"],
    "info": ["info", "information", "about", "tell me more"],
    "help": ["help", "what can you do", "how does this work"],
    "confirm": ["yes", "confirm", "proceed", "ok"],
    "cancel": ["no", "cancel", "stop", "never mind"],
    "select_by_number": ["1", "2", "3", "4", "5", "first", "second", "third"],
}

_FALLBACK_RESULT = {
    "intent": "other",
    "search_query": None,
    "products": [],
    "quantity_updates": [],
    "selection_index": None,
    "customer_name": None,
    "confidence": 0.0,
    "clarification_needed": False,
}


def _get_deepseek_client():
    """Lazy-init DeepSeek client. Raises clearly if key is missing."""
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY environment variable is not set")
    from openai import AsyncOpenAI
    return AsyncOpenAI(api_key=api_key, base_url="https://api.deepseek.com")


async def _call_llm(
    messages: List[Dict[str, str]],
    temperature: float = 0.1,
    max_retries: int = 2,
) -> Dict[str, Any]:
    client = _get_deepseek_client()

    system_prompt = {
        "role": "system",
        "content": (
            "You are an intent classifier for a WhatsApp store. "
            "Return ONLY valid JSON with this exact shape:\n"
            "{\n"
            '  "intent": "greeting" | "product_search" | "add_to_cart" | "view_cart" | '
            '"remove_from_cart" | "update_quantity" | "clear_cart" | "checkout" | '
            '"info" | "help" | "confirm" | "cancel" | "select_by_number" | "other",\n'
            '  "search_query": string | null,\n'
            '  "products": [{"name": string, "quantity": number}],\n'
            '  "quantity_updates": [{"name": string, "quantity": number, "item_index": number}],\n'
            '  "selection_index": number | null,\n'
            '  "customer_name": string | null,\n'
            '  "confidence": number (0.0 to 1.0),\n'
            '  "clarification_needed": boolean\n'
            "}\n"
            "No markdown. No explanation. JSON only."
        ),
    }

    full_messages = [system_prompt] + messages

    for attempt in range(max_retries):
        try:
            response = await client.chat.completions.create(
                model="deepseek-chat",
                messages=full_messages,
                temperature=temperature,
                response_format={"type": "json_object"},
            )

            raw = response.choices[0].message.content.strip()
            if raw.startswith("```"):
                m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
                raw = m.group(1).strip() if m else raw.replace("```json", "").replace("```", "").strip()

            result = json.loads(raw)

            for field, default in [
                ("intent", "other"),
                ("products", []),
                ("quantity_updates", []),
                ("selection_index", None),
                ("confidence", 0.8),
                ("clarification_needed", False),
            ]:
                if field not in result:
                    result[field] = default

            return result

        except json.JSONDecodeError as e:
            logger.warning("DeepSeek bad JSON (attempt %d): %s", attempt + 1, e)
            if attempt == max_retries - 1:
                return dict(_FALLBACK_RESULT)

        except Exception as e:
            logger.error("DeepSeek API error (attempt %d): %s", attempt + 1, e)
            if attempt == max_retries - 1:
                return dict(_FALLBACK_RESULT)
            import asyncio
            await asyncio.sleep(1)

    return dict(_FALLBACK_RESULT)


def _rule_based_classifier(message: str) -> Dict[str, Any]:
    message_lower = message.lower().strip()

    if message_lower.isdigit() and 1 <= int(message_lower) <= 9:
        return {**_FALLBACK_RESULT, "intent": "select_by_number", "selection_index": int(message_lower), "confidence": 0.9}

    change_match = re.search(r"(?:change|update|make it|set to)\s+(\d+)", message_lower)
    if change_match:
        return {
            **_FALLBACK_RESULT,
            "intent": "update_quantity",
            "quantity_updates": [{"name": None, "quantity": int(change_match.group(1)), "item_index": None}],
            "confidence": 0.7,
            "clarification_needed": True,
        }

    for intent, keywords in INTENT_KEYWORDS.items():
        for keyword in keywords:
            if keyword in message_lower or message_lower == keyword:
                return {
                    **_FALLBACK_RESULT,
                    "intent": intent,
                    "search_query": message if intent == "product_search" else None,
                    "confidence": 0.6,
                }

    return dict(_FALLBACK_RESULT)


def _build_context(
    store_name: str,
    history: Optional[List[Dict[str, str]]],
    cart_summary: Optional[Dict[str, Any]],
    product_context: Optional[List[Dict[str, Any]]],
    last_intent: Optional[str],
) -> str:
    parts = [f"Store: {store_name}"]

    hour = datetime.now().hour
    parts.append(f"Time: {'morning' if hour < 12 else 'afternoon' if hour < 17 else 'evening'}")

    if cart_summary and cart_summary.get("item_count", 0) > 0:
        parts.append(f"Cart: {cart_summary['item_count']} items, total {CURRENCY_SYMBOL}{cart_summary.get('total', 0):,.2f}")
        if cart_summary.get("items"):
            for i, item in enumerate(cart_summary["items"][:5], 1):
                parts.append(f"  {i}. {item['quantity']}x {item.get('product_name', item.get('name', 'item'))}")
    else:
        parts.append("Cart: empty")

    if product_context:
        names = [p["name"] for p in product_context[:5] if p.get("name")]
        if names:
            parts.append(f"Recent products: {', '.join(names)}")

    if history:
        for msg in history[-4:]:
            role = "Customer" if msg.get("role") == "user" else "Store"
            content = (msg.get("content", "")[:50] + "...") if len(msg.get("content", "")) > 50 else msg.get("content", "")
            parts.append(f"{role}: {content}")

    if last_intent and last_intent != "other":
        parts.append(f"Last action: {last_intent}")

    return "\n".join(parts)


async def classify_intent(
    *,
    message: str,
    store_name: str,
    history: Optional[List[Dict[str, str]]] = None,
    cart_summary: Optional[Dict[str, Any]] = None,
    product_context: Optional[List[Dict[str, Any]]] = None,
    last_intent: Optional[str] = None,
    use_fallback: bool = False,
) -> Dict[str, Any]:
    history = history or []
    message_lower = message.lower().strip()

    # Fast path: unambiguous single-token intents
    if message_lower.isdigit() and 1 <= int(message_lower) <= 9:
        return {**_FALLBACK_RESULT, "intent": "select_by_number", "selection_index": int(message_lower), "confidence": 1.0}

    if message_lower in ("hi", "hello", "hey"):
        return {**_FALLBACK_RESULT, "intent": "greeting", "confidence": 1.0}

    if message_lower in ("help", "what can you do"):
        return {**_FALLBACK_RESULT, "intent": "help", "confidence": 1.0}

    if use_fallback:
        return _rule_based_classifier(message)

    context = _build_context(store_name, history, cart_summary, product_context, last_intent)

    system_prompt = f"""You are an intent classifier for {store_name}. Return ONLY JSON.

CONTEXT:
{context}

RULES:
1. Return valid JSON matching this structure:
   {{
     "intent": one of {sorted(ALLOWED_INTENTS)},
     "search_query": string or null,
     "products": [{{"name": string, "quantity": number}}],
     "quantity_updates": [{{"name": string or null, "quantity": number, "item_index": number or null}}],
     "selection_index": number or null,
     "customer_name": string or null,
     "confidence": 0.0–1.0,
     "clarification_needed": boolean
   }}
2. Quantity defaults to 1
3. customer_name only if introduced explicitly"""

    try:
        result = await _call_llm([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message},
        ])

        # Sanitise products
        cleaned_products = []
        for p in (result.get("products") or []):
            if isinstance(p, dict) and p.get("name"):
                try:
                    qty = max(1, min(99, int(p.get("quantity", 1))))
                except (TypeError, ValueError):
                    qty = 1
                cleaned_products.append({"name": str(p["name"]).strip(), "quantity": qty})

        # Sanitise quantity_updates
        cleaned_updates = []
        for u in (result.get("quantity_updates") or []):
            if isinstance(u, dict):
                try:
                    qty = max(0, min(99, int(u.get("quantity", 1))))
                except (TypeError, ValueError):
                    qty = 1
                cleaned_updates.append({
                    "name": str(u["name"]) if u.get("name") else None,
                    "quantity": qty,
                    "item_index": u.get("item_index") if isinstance(u.get("item_index"), int) else None,
                })

        # Sanitise selection_index
        sel = result.get("selection_index")
        try:
            sel = int(sel) if sel is not None else None
            if sel is not None and not (1 <= sel <= 99):
                sel = None
        except (TypeError, ValueError):
            sel = None

        intent = result.get("intent", "other")
        if intent not in ALLOWED_INTENTS:
            intent = "other"

        try:
            confidence = max(0.0, min(1.0, float(result.get("confidence", 0.8))))
        except (TypeError, ValueError):
            confidence = 0.5

        return {
            "intent": intent,
            "search_query": result.get("search_query"),
            "products": cleaned_products,
            "quantity_updates": cleaned_updates,
            "selection_index": sel,
            "customer_name": result.get("customer_name"),
            "confidence": confidence,
            "clarification_needed": bool(result.get("clarification_needed", False)),
        }

    except Exception as e:
        logger.error("Intent classification failed, using fallback: %s", e)
        return _rule_based_classifier(message)
