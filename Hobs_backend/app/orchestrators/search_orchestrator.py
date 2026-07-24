# app/orchestrators/search_orchestrator.py

import logging
import re
from typing import List, Dict, Any, Optional

from app.conversation.humanizer import Humanizer
from app.orchestrators.context import ConversationContext

logger = logging.getLogger(__name__)

DISPLAY_THRESHOLD = 65.0
STRONG_THRESHOLD  = 80.0
MAX_DISPLAY       = 5

_AFFIRMATIVE_PATTERNS = re.compile(
    r"^(?:yes|yeah|yep|yup|ya|sure|ok|okay|add it|add|go ahead|proceed|"
    r"definitely|of course|please|pls|do it|yes please|yes pls|"
    r"i'd have|i'll have|i'll take|give me|gimme|oya|"
    r"i want it|add it please|put it in|add am|put am)$",
    re.IGNORECASE,
)

_TRAIL_PHRASES_RE = re.compile(
    r"\s+(?:is good|would be good|is fine|sounds good|sounds great|"
    r"please|will do|for me|for now|that'?s fine|that'?s good|"
    r"pls|plz|is perfect|is great|abeg|now now)\s*\.?$",
    re.IGNORECASE,
)


class SearchOrchestrator:

    def __init__(self, context: ConversationContext):
        self.ctx          = context
        self.matcher      = context.matcher
        self.memory       = context.memory
        self.cart_service = context.cart_service

        self.merchant_id  = str(context.tenant.merchant_id)
        self.client_id    = str(context.tenant.client_id)
        self.user_id      = context.user_phone
        self.style        = context.tenant.persona_style

    # ==========================================================
    # PRODUCT SEARCH
    # ==========================================================

    async def search_products(self, query: str) -> str:

        if not query or not query.strip():
            return Humanizer.fallback(self.style)

        query = _TRAIL_PHRASES_RE.sub("", query.strip()).strip()
        if not query:
            return Humanizer.fallback(self.style)

        current_mode = await self.memory.get_mode()
        if current_mode in ("confirming_qty", "selecting"):
            await self.memory.set_mode("idle")
            await self.memory.clear_choices()
            await self.memory.clear_temp()

        from app.services.deepseek_service import _WORD_NUMS
        _qty_inline: Optional[int] = None
        _stripped   = query.strip()

        digit_match = re.match(r"^(\d+)\s+(.+)$", _stripped)
        if digit_match:
            _qty_inline = max(1, min(99, int(digit_match.group(1))))
            _stripped   = digit_match.group(2).strip()
        else:
            for _word, _val in sorted(_WORD_NUMS.items(), key=lambda x: -len(x[0])):
                _pat = re.compile(r"^" + re.escape(_word) + r"\s+(.+)$", re.IGNORECASE)
                _m   = _pat.match(_stripped)
                if _m:
                    _qty_inline = max(1, min(99, _val))
                    _stripped   = _m.group(1).strip()
                    break

        if _qty_inline:
            await self.memory.set("pending_selection_qty", _qty_inline)
            query = _stripped

        matches = await self.matcher.search(
            query=query,
            merchant_id=self.merchant_id,
            client_id=self.client_id,
            limit=MAX_DISPLAY + 3,
        )

        if not matches:
            try:
                _tokens = [t for t in query.split() if len(t) > 2]
                _broad = []
                for _tok in _tokens[:3]:
                    _tok_matches = await self.matcher.search(
                        query=_tok,
                        merchant_id=self.merchant_id,
                        client_id=self.client_id,
                        limit=2,
                    )
                    for _m in _tok_matches:
                        if _m not in _broad:
                            _broad.append(_m)
                _broad = _broad[:3]
            except Exception:
                _broad = []

            if _broad:
                _suggestions = ", ".join(f"*{m.name}*" for m in _broad)
                return Humanizer._pick([
                    f"We don't have *{query}* right now, but you might like: {_suggestions}. Interested in any of these?",
                    f"No exact match for *{query}*, but we do have {_suggestions} — want one of those instead?",
                    f"*{query}* isn't available, but here are some alternatives: {_suggestions}. Shall I add one?",
                ])

            # FIX: fire name prompt on no-results path too — customer is engaging
            # but will never hit _add_confirmed from here.
            await self._maybe_ask_name_after_reply()
            return Humanizer.no_results(query, self.style)

        from app.services.fuzzy_match import FuzzyMatcher as _FM
        variant_group = _FM.detect_variant_group(matches, query)
        if variant_group:
            display_variants = matches[:MAX_DISPLAY]
            await self.memory.set_choices([
                {
                    "product_id": str(m.product_id),
                    "name":       m.name,
                    "price":      float(m.price) if m.price else 0.0,
                }
                for m in display_variants
            ])
            await self.memory.set_mode("selecting")
            await self.memory.set_last_search(query)
            return Humanizer.present_variants(
                variants=display_variants,
                query=query,
                style=self.style,
            )

        good_matches = [m for m in matches if getattr(m, "score", 0) >= DISPLAY_THRESHOLD]
        if not good_matches:
            good_matches = matches[:3]

        display = good_matches[:MAX_DISPLAY]

        if len(display) == 1 and getattr(display[0], "score", 0) >= STRONG_THRESHOLD:
            top = display[0]
            if _qty_inline:
                return await self._add_confirmed(top, _qty_inline)
            await self.memory.update({
                "mode": "confirming_qty",
                "temp": {
                    "pending_product": {
                        "product_id": str(top.product_id),
                        "name":       top.name,
                        "price":      float(top.price or 0),
                    }
                },
            })
            return Humanizer.confirm_quantity_prompt(top.name, float(top.price or 0))

        has_more = len(matches) >= MAX_DISPLAY
        await self.memory.set_choices([
            {
                "product_id": str(m.product_id),
                "name":       m.name,
                "price":      float(m.price) if m.price else 0.0,
            }
            for m in display
        ])
        await self.memory.set_mode("selecting")
        await self.memory.set_last_search(query)

        # FIX: fire name prompt on browse path — customer is engaging but not adding yet.
        # Previously only _add_confirmed triggered this so browsers were never named.
        await self._maybe_ask_name_after_reply()

        return Humanizer.present_choices_conversational(
            choices=display,
            query=query,
            has_more=has_more,
            style=self.style,
        )

    # ==========================================================
    # HANDLE SELECTION (mode: selecting)
    # ==========================================================

    async def handle_selection(self, user_input: str) -> str:

        choices = await self.memory.get_choices()

        if not choices:
            await self.memory.set_mode("idle")
            return Humanizer.search_expired()

        text       = user_input.strip()
        text_lower = text.lower()

        if text_lower in ("cancel", "nevermind", "never mind", "stop",
                          "no", "nah", "nothing", "forget it"):
            await self.memory.clear_choices()
            await self.memory.set_mode("idle")
            return Humanizer._pick([
                "No problem! What else can I help you with?",
                "All good. What would you like to look for?",
            ])

        selected = _fuzzy_pick_choice(text_lower, choices)

        if selected is None:
            await self.memory.clear_choices()
            await self.memory.set_mode("idle")
            return await self.search_products(text)

        pending_qty_raw = await self.memory.get("pending_selection_qty")
        try:
            quantity = max(1, min(99, int(pending_qty_raw))) if pending_qty_raw else 1
        except (TypeError, ValueError):
            quantity = 1

        cart = await self.cart_service.get_active_cart(
            merchant_id=self.merchant_id,
            client_id=self.client_id,
            user_id=self.user_id,
        )
        if not cart:
            cart = await self.cart_service.create_cart(
                merchant_id=self.merchant_id,
                client_id=self.client_id,
                user_id=self.user_id,
            )

        from app.schemas.cart import CartItemSchema

        updated_cart = await self.cart_service.add_item(
            merchant_id=self.merchant_id,
            client_id=self.client_id,
            cart_id=cart.id,
            item=CartItemSchema(
                product_id=selected["product_id"],
                quantity=quantity,
                price_at_add=selected.get("price", 0),
            ),
        )

        summary = self.cart_service._build_summary(updated_cart)

        await self.memory.clear_choices()
        await self.memory.delete("pending_selection_qty")
        await self.memory.set_mode("shopping")
        await self.memory.set("last_added_product", selected["name"])

        return Humanizer.added_to_cart(
            selected["name"],
            summary["item_count"],
            summary["total"],
            style=self.style,
        )

    # ==========================================================
    # HANDLE QUANTITY CONFIRMATION (mode: confirming_qty)
    # ==========================================================

    async def handle_qty_confirmation(self, user_input: str) -> str:
        pending = await self.memory.get_temp_data("pending_product")

        if not pending:
            await self.memory.set_mode("idle")
            return Humanizer.search_expired()

        text = user_input.strip().lower()

        _stated_qty = await self.memory.get("pending_selection_qty")
        try:
            _stated_qty = max(1, min(99, int(_stated_qty))) if _stated_qty else None
        except (TypeError, ValueError):
            _stated_qty = None

        if _AFFIRMATIVE_PATTERNS.match(text):
            quantity = _stated_qty if _stated_qty else 1
        else:
            from app.services.deepseek_service import _extract_number_word
            quantity = _extract_number_word(user_input)

            if quantity is None:
                pending_name = (pending.get("name") or "").lower()
                if pending_name and (
                    text == pending_name
                    or pending_name in text
                    or text in pending_name
                ):
                    quantity = 1
                else:
                    await self.memory.delete("pending_product")
                    await self.memory.set_mode("idle")
                    return await self.search_products(user_input)

        quantity = max(1, min(quantity, 99))
        return await self._add_confirmed(pending, quantity)

    # ==========================================================
    # INTERNAL: add a confirmed product to cart
    # ==========================================================

    async def _add_confirmed(self, product: Dict, quantity: int) -> str:
        """Add a product dict (or match object) with known quantity to cart."""
        if isinstance(product, dict):
            product_id = product["product_id"]
            name       = product["name"]
            price      = product.get("price", 0)
        else:
            product_id = str(product.product_id)
            name       = product.name
            price      = float(product.price or 0)

        try:
            cart = await self.cart_service.get_active_cart(
                merchant_id=self.merchant_id,
                client_id=self.client_id,
                user_id=self.user_id,
            )
            if not cart:
                cart = await self.cart_service.create_cart(
                    merchant_id=self.merchant_id,
                    client_id=self.client_id,
                    user_id=self.user_id,
                )

            from app.schemas.cart import CartItemSchema

            updated_cart = await self.cart_service.add_item(
                merchant_id=self.merchant_id,
                client_id=self.client_id,
                cart_id=cart.id,
                item=CartItemSchema(
                    product_id=product_id,
                    quantity=quantity,
                    price_at_add=price,
                ),
            )

            summary = self.cart_service._build_summary(updated_cart)

            await self.memory.delete("pending_product")
            await self.memory.set_mode("shopping")
            await self.memory.clear_choices()
            await self.memory.set("last_added_product", name)

            base_reply = Humanizer.single_result_added(
                product_name=name,
                price=price,
                total=summary["total"],
            )

            # FIX: use shared helper so name prompt fires consistently
            # regardless of which path led here.
            name_suffix = await self._consume_name_prompt()
            if name_suffix:
                return base_reply + name_suffix

            return base_reply

        except Exception as e:
            logger.error("_add_confirmed failed for %s: %s", name, e)
            await self.memory.delete("pending_product")
            await self.memory.set_mode("idle")
            return Humanizer.error("generic")

    # ==========================================================
    # AUTO-ADD (internal fallback)
    # ==========================================================

    async def _auto_add(self, match, query: str) -> str:
        try:
            return await self._add_confirmed(match, 1)
        except Exception as e:
            logger.error("Auto-add failed for %s: %s", getattr(match, "name", "?"), e)
            return Humanizer.single_result(
                getattr(match, "name", "?"),
                float(getattr(match, "price", 0) or 0),
            )

    # ==========================================================
    # FIX: NAME PROMPT HELPERS
    #
    # Previously pending_name_prompt was only consumed inside _add_confirmed,
    # so a customer who browsed or searched without adding was never asked
    # for their name — they could complete a full order anonymously.
    #
    # Now:
    # - _add_confirmed calls _consume_name_prompt() → appends question inline,
    #   sets mode to awaiting_name (overrides "shopping").
    # - search_products calls _maybe_ask_name_after_reply() on the browse and
    #   no-results paths → sets mode to awaiting_name so the NEXT message the
    #   customer sends is intercepted by the name handler in webhook.py.
    #   We don't append text here because the reply is already constructed.
    # ==========================================================

    async def _consume_name_prompt(self) -> str | None:
        """
        Consume pending_name_prompt and return the suffix to append to the reply.
        Returns None if the flag is not set.
        Sets mode to awaiting_name so the next message is handled by the name handler.
        """
        pending = await self.memory.get("pending_name_prompt", False)
        if not pending:
            return None
        await self.memory.delete("pending_name_prompt")
        await self.memory.set_mode("awaiting_name")
        return "\n\nAlso — I didn't catch your name! What should I call you? 😊"

    async def _maybe_ask_name_after_reply(self) -> None:
        """
        For non-add paths (browse results, no-results): if the name prompt is
        pending and the customer has sent at least one prior message, consume
        the flag and set awaiting_name so their NEXT message triggers the handler.

        The interaction counter (_interaction_count) is incremented here so we
        don't fire the prompt on their very first browse before they've finished
        expressing what they want.
        """
        pending = await self.memory.get("pending_name_prompt", False)
        if not pending:
            return

        count = await self.memory.get("_interaction_count", 0)
        await self.memory.set("_interaction_count", count + 1)

        if count < 1:
            # First interaction — let them finish their thought first
            return

        await self.memory.delete("pending_name_prompt")
        await self.memory.set_mode("awaiting_name")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _fuzzy_pick_choice(text_lower: str, choices: List[Dict]) -> Optional[Dict]:
    """
    Match customer reply against stored choices by name.
    Priority: exact → substring → token overlap.
    """
    for c in choices:
        if text_lower == c["name"].lower():
            return c

    for c in choices:
        name_lower = c["name"].lower()
        if text_lower in name_lower or name_lower in text_lower:
            return c

    input_tokens = {t for t in text_lower.split() if len(t) > 2}
    best_overlap = 0
    best_choice  = None
    for c in choices:
        name_tokens = {t for t in c["name"].lower().split() if len(t) > 2}
        overlap     = len(input_tokens & name_tokens)
        if overlap > best_overlap:
            best_overlap = overlap
            best_choice  = c

    if best_overlap >= 1:
        return best_choice

    return None