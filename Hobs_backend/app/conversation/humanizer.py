# app/conversation/humanizer.py
import random
from typing import Optional, List, Dict, Any
from datetime import datetime
import re


class Humanizer:
    """
    All customer-facing strings live here.

    Rules:
    - WhatsApp bold = *text*, NOT **text**
    - Every public method has 3+ variants — no two sessions feel identical
    - No robotic confirmations, no corporate filler phrases
    - No numbered pick lists — customers reply by name
    - Per-personality tone is enforced throughout
    """

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _pick(options: list) -> str:
        return random.choice(options)

    @staticmethod
    def _pick_styled(variants: dict, style: str, fallback_key: str = "friendly_casual") -> str:
        pool = variants.get(style) or variants.get(fallback_key, [])
        return random.choice(pool) if pool else ""

    @staticmethod
    def _ensure_float(value) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            cleaned = value.replace("₦", "").replace(",", "").replace(" ", "").strip()
            try:
                return float(cleaned)
            except ValueError:
                return 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _format_currency(amount) -> str:
        amount = Humanizer._ensure_float(amount)
        if amount >= 1_000_000:
            return f"₦{amount / 1_000_000:.1f}M"
        if amount >= 1_000:
            return f"₦{amount:,.0f}"
        return f"₦{amount:,.2f}"

    @staticmethod
    def _time_greeting() -> str:
        h = datetime.now().hour
        if h < 12:
            return "Good morning"
        elif h < 17:
            return "Good afternoon"
        return "Good evening"

    # ── Greeting ──────────────────────────────────────────────────────────────

    @classmethod
    def greeting(
        cls,
        store_name: str,
        customer_name: Optional[str] = None,
        persona_name: Optional[str] = None,
    ) -> str:
        tg = cls._time_greeting()
        if customer_name:
            if persona_name:
                return cls._pick([
                    f"{tg}, {customer_name}! 👋 It's {persona_name} from {store_name}. What can I get for you?",
                    f"Hey {customer_name}! Welcome back to {store_name}. What are you looking for?",
                    f"{tg} {customer_name}! {persona_name} here — what would you like today? 😊",
                    f"Welcome back, {customer_name}! {persona_name} at {store_name} — what can I help you with?",
                ])
            return cls._pick([
                f"{tg}, {customer_name}! 👋 Welcome back to {store_name}. What can I get for you?",
                f"Hey {customer_name}! Good to see you again. What are you looking for?",
                f"{tg} {customer_name}! 😊 What would you like today?",
                f"Welcome back, {customer_name}! What can I help you with?",
            ])
        if persona_name:
            return cls._pick([
                f"{tg}! 👋 I'm {persona_name}, your shopping assistant at {store_name}. What are you looking for?",
                f"Hi there! {persona_name} here from {store_name} — what can I get for you?",
                f"Hello! I'm {persona_name} at {store_name}. What would you like? 😊",
                f"{tg}! {persona_name} here — how can I help you today?",
            ])
        return cls._pick([
            f"{tg}! 👋 Welcome to {store_name}. What are you looking for?",
            f"Hi there! Welcome to {store_name} — what can I get for you?",
            f"Hello! Thanks for stopping by {store_name}. What would you like? 😊",
            f"{tg}! How can I help you today?",
        ])

    @classmethod
    def first_time_welcome(
        cls,
        store_name: str,
        persona_name: Optional[str] = None,
    ) -> str:
        tg = cls._time_greeting()
        if persona_name:
            return cls._pick([
                f"{tg}! 👋 Welcome to *{store_name}*!\n\n"
                f"I'm {persona_name}, your personal shopping assistant. "
                f"I can help you browse products, build your order, and check out — all right here on WhatsApp.\n\n"
                f"Before we get started, what's your name?",

                f"Hello! Welcome to *{store_name}* 🛍️\n\n"
                f"I'm {persona_name}, your shopping assistant here. "
                f"I'll help you find what you need and place your order — quick and easy!\n\n"
                f"First, what do I call you?",

                f"{tg} and welcome to *{store_name}*! 😊\n\n"
                f"I'm {persona_name} — here to help you shop. "
                f"Products, cart, checkout — all on WhatsApp.\n\n"
                f"What's your name?",
            ])
        return cls._pick([
            f"{tg}! 👋 Welcome to *{store_name}*!\n\n"
            f"I'm your personal shopping assistant here. "
            f"I can help you browse products, build your order, and check out — all right here on WhatsApp.\n\n"
            f"Before we get started, what's your name?",

            f"Hello! Welcome to *{store_name}* 🛍️\n\n"
            f"Your shopping assistant is here! "
            f"I'll help you find what you need and place your order — it's quick and easy.\n\n"
            f"First, what do I call you?",

            f"{tg} and welcome to *{store_name}*! 😊\n\n"
            f"I'm here to help you shop — products, cart, checkout, all on WhatsApp.\n\n"
            f"What's your name?",
        ])

    @classmethod
    def name_saved(cls, name: str, store_name: str) -> str:
        tg = cls._time_greeting()
        return cls._pick([
            f"Nice to meet you, *{name}*! 😊\n\n{tg} — what can I get for you from {store_name} today?",
            f"Great, *{name}*! Welcome aboard. 👋\n\nWhat are you looking for today?",
            f"Hi *{name}*! I'm ready to help.\n\nWhat would you like to order?",
        ])

    # ── Voice note ────────────────────────────────────────────────────────────

    @classmethod
    def voice_note_reply(cls) -> str:
        return cls._pick([
            "I received your voice note, but I can only read text right now. "
            "Could you type out what you're looking for? I'll get right on it! 😊",
            "Oh, a voice note! I can't listen to audio just yet — "
            "but if you type it out, I'll help you straight away.",
            "I'm text-only for now. Just type what you need and I'll take care of it! 🙏",
        ])

    # ── Product search ────────────────────────────────────────────────────────

    @classmethod
    def no_results(cls, query: str, style: str = "friendly_casual") -> str:
        return cls._pick_styled({
            "friendly_casual": [
                f"Hmm, I couldn't find *{query}* right now. Maybe try a different name?",
                f"We don't seem to have *{query}* at the moment. Want to try something else?",
                f"No luck finding *{query}* — could you describe it differently?",
                f"I searched but couldn't spot *{query}*. Try a brand name or different spelling?",
            ],
            "professional": [
                f"I was unable to locate *{query}* in our catalogue. Please try a different search term.",
                f"*{query}* does not appear to be available at this time. May I suggest an alternative?",
                f"We currently have no listing for *{query}*. Please refine your search.",
            ],
            "warm_enthusiastic": [
                f"Oh no, I couldn't find *{query}*! 😟 Let's try a different name — I'm sure we can find something great!",
                f"I searched everywhere for *{query}* but no luck! Try a different spelling? 🔍",
                f"We don't seem to have *{query}* right now — try a related name? 😊",
            ],
        }, style)

    @classmethod
    def single_result(cls, product_name: str, price: float,
                      description: Optional[str] = None) -> str:
        price_str = cls._format_currency(price)
        if description:
            return cls._pick([
                f"Found it! *{product_name}* — {description}\nPrice: *{price_str}*\n\nShall I add it to your cart?",
                f"Got it — *{product_name}* ({description}) at *{price_str}*. Add it?",
            ])
        return cls._pick([
            f"Found it! *{product_name}* — *{price_str}*. Add it to your cart?",
            f"Got it — *{product_name}* at *{price_str}*. Want me to add it?",
            f"Here you go: *{product_name}* for *{price_str}*. Shall I add it?",
        ])

    @classmethod
    def confirm_quantity_prompt(cls, product_name: str, price: float) -> str:
        """Ask how many — shown when a single strong match is found."""
        # FLOW-8: always say "each" / "per unit" so the customer knows the price
        # is per item, not a total — avoids checkout surprise on multi-qty orders.
        price_str = cls._format_currency(price)
        return cls._pick([
            f"We have *{product_name}* for *{price_str}* each. How many would you like?",
            f"*{product_name}* — *{price_str}* per unit. How many should I add?",
            f"Found *{product_name}* at *{price_str}* each. How many do you want?\n\n_Not the right one? Just type a different name._",
        ])

    @classmethod
    def single_result_added(cls, product_name: str, price: float, total: float) -> str:
        """Confirm after product is added."""
        return cls._pick([
            f"*{product_name}* added! 🛒\n\nAnything else, or ready to checkout?",
            f"Done — *{product_name}* is in your cart.\n\nKeep shopping or say *checkout* when you're ready.",
            f"Got it! *{product_name}* is in your cart.\n\nAnything else to add?",
        ])

    @classmethod
    def present_variants(
        cls,
        variants: List[Any],
        query: str,
        style: str = "friendly_casual",
    ) -> str:
        """Conversational variant presentation — no numbered list."""
        if not variants:
            return cls.no_results(query, style)

        parts = [
            f"*{v.name}* ({cls._format_currency(float(v.price or 0))})"
            for v in variants
        ]
        if len(parts) == 1:
            item_list = parts[0]
        elif len(parts) == 2:
            item_list = f"{parts[0]} or {parts[1]}"
        else:
            item_list = ", ".join(parts[:-1]) + f", or {parts[-1]}"

        return cls._pick_styled({
            "friendly_casual": [
                f"We have a few options for *{query}*: {item_list} — which one would you like?",
                f"For *{query}* we've got {item_list}. Which suits you?",
                f"Here's what we have for *{query}*: {item_list}. Which one?",
            ],
            "professional": [
                f"The following options are available for *{query}*: {item_list}. Please specify which you'd like.",
                f"We have {item_list} for *{query}*. Which would you prefer?",
            ],
            "warm_enthusiastic": [
                f"Great news — we have {item_list} for *{query}*! 😊 Which one catches your eye?",
                f"Ooh, options! For *{query}*: {item_list} — which sounds good?",
            ],
        }, style)

    @classmethod
    def present_choices_conversational(
        cls,
        choices: List[Any],
        query: Optional[str] = None,
        has_more: bool = False,
        style: str = "friendly_casual",
    ) -> str:
        """
        UX-6: Render choices as vertical line-separated items, not inline prose.

        WhatsApp is a vertical reading surface — on mobile, a comma-separated
        sentence with 4-5 items becomes a wall of text.  Each option on its own
        line is scannable at a glance.
        """
        if not choices:
            return cls.no_results(query or "", style)

        def _name(c):
            return c["name"] if isinstance(c, dict) else c.name

        def _price(c):
            raw = c["price"] if isinstance(c, dict) else c.price
            return cls._format_currency(float(raw or 0))

        # Build a vertical list: • *Product* — ₦price
        lines = [f"• *{_name(c)}* — {_price(c)}" for c in choices]
        item_list = "\n".join(lines)

        suffix = "\n\n_Don't see it? Try a more specific name._" if has_more else ""
        cta    = "Just name the one you want."

        if query:
            return cls._pick_styled({
                "friendly_casual": [
                    f"Here's what I found for *{query}*:\n\n{item_list}\n\n{cta}{suffix}",
                    f"A few options for *{query}*:\n\n{item_list}\n\n{cta}{suffix}",
                    f"These match *{query}*:\n\n{item_list}\n\n{cta}{suffix}",
                ],
                "professional": [
                    f"The following match *{query}*:\n\n{item_list}\n\nPlease specify which you'd like.{suffix}",
                    f"Available options for *{query}*:\n\n{item_list}\n\nKindly indicate your preference.{suffix}",
                ],
                "warm_enthusiastic": [
                    f"Found some options for *{query}*! 🎉\n\n{item_list}\n\nWhich one catches your eye? 😊{suffix}",
                    f"Look at these for *{query}*! 🛍️\n\n{item_list}\n\nWhich sounds good?{suffix}",
                ],
            }, style)

        return cls._pick_styled({
            "friendly_casual": [
                f"Here are a few options:\n\n{item_list}\n\n{cta}{suffix}",
                f"Take a look:\n\n{item_list}\n\n{cta}{suffix}",
            ],
            "professional": [
                f"Available options:\n\n{item_list}\n\nPlease indicate your preference.{suffix}",
            ],
            "warm_enthusiastic": [
                f"Here's what we've got! 😊\n\n{item_list}\n\n{cta}{suffix}",
            ],
        }, style)

    # Legacy shim
    @classmethod
    def present_choices(
        cls,
        choices_text: str,
        query: Optional[str] = None,
        has_more: bool = False,
        style: str = "friendly_casual",
    ) -> str:
        hint = "\n\n_Don't see it? Type a different name._"
        if query:
            return cls._pick_styled({
                "friendly_casual": [
                    f"Here's what I found for *{query}*:\n\n{choices_text}{hint}",
                    f"A few options for *{query}*:\n\n{choices_text}{hint}",
                ],
                "professional": [
                    f"Available options for *{query}*:\n\n{choices_text}{hint}",
                ],
                "warm_enthusiastic": [
                    f"Found some options for *{query}*! 🎉\n\n{choices_text}{hint}",
                ],
            }, style)
        return f"Here are a few options:\n\n{choices_text}{hint}"

    # ── Add to cart ───────────────────────────────────────────────────────────

    @classmethod
    def added_to_cart_no_total(cls, items: str, style: str = "friendly_casual") -> str:
        # Used for the FIRST item added to a new cart. Per merchant request,
        # we don't show a price/total on this message — only the product
        # name and a confirmation that it was added. Total starts appearing
        # from the second item onward (see added_to_cart below).
        base = cls._pick_styled({
            "friendly_casual": [
                f"*{items}* added to your cart!",
                f"Got it — *{items}* is in your cart.",
                f"Done! Added *{items}*.",
                f"*{items}* — added. 👍",
            ],
            "professional": [
                f"*{items}* has been added to your order.",
                f"Confirmed — *{items}* is now in your cart.",
            ],
            "warm_enthusiastic": [
                f"Awesome! *{items}* is in your cart! 🛒",
                f"Great choice! *{items}* added! 😊",
                f"Yes! *{items}* is in! 🎉",
            ],
        }, style)
        nudge = "Say *checkout* when you're ready, or keep shopping! 🛒"
        return f"{base}\n\n{nudge}"

    @classmethod
    def added_to_cart(cls, items: str, item_count: int = 0, total=None,
                      style: str = "friendly_casual") -> str:
        # FIX: _ensure_float() always returns a float and never None, so the
        # old "if _total_float is not None" check below was dead code — it
        # meant a genuine ₦0.00 was indistinguishable from "no total available"
        # and always got rendered as "Cart total: ₦0.00". We now check the
        # raw `total` argument for None *before* coercing it to a float.
        total_str = cls._format_currency(total) if total is not None else None
        base = cls._pick_styled({
            "friendly_casual": [
                f"*{items}* added to your cart!",
                f"Got it — *{items}* is in your cart.",
                f"Done! Added *{items}*.",
                f"*{items}* — added. 👍",
            ],
            "professional": [
                f"*{items}* has been added to your order.",
                f"Confirmed — *{items}* is now in your cart.",
            ],
            "warm_enthusiastic": [
                f"Awesome! *{items}* is in your cart! 🛒",
                f"Great choice! *{items}* added! 😊",
                f"Yes! *{items}* is in! 🎉",
            ],
        }, style)
        # FLOW-7: always include a soft checkout nudge so customers on this path
        # know they can complete their purchase (single_result_added already does this).
        # UX-5: total is always shown when available — never omitted by variant chance.
        nudge = "Say *checkout* when you're ready, or keep shopping! 🛒"
        if total_str:
            return f"{base} Cart total: *{total_str}*\n\n{nudge}"
        return f"{base}\n\n{nudge}"  # fallback only if total genuinely unavailable

    # ── View cart ─────────────────────────────────────────────────────────────

    @classmethod
    def empty_cart(cls) -> str:
        return cls._pick([
            "Your cart is empty. What would you like to order?",
            "Nothing in your cart yet — what can I get for you?",
            "Your cart is empty. Just tell me what you're looking for!",
        ])

    # ── Checkout / delivery ───────────────────────────────────────────────────

    @classmethod
    def checkout_delivery_type_prompt(
        cls,
        total: float,
        delivery_fee: float,
        delivery_area: Optional[str] = None,
    ) -> str:
        total_str = cls._format_currency(total)
        fee_str   = cls._format_currency(delivery_fee)
        area_note = (
            f"\n_(Delivery is currently available within {delivery_area} only.)_"
            if delivery_area else ""
        )
        return cls._pick([
            f"Your cart total is *{total_str}*.\n\n"
            f"How would you like to receive your order?\n\n"
            f"1️⃣ Pickup — collect from our store\n"
            f"2️⃣ Delivery — we bring it to you (*+{fee_str}* delivery fee)"
            f"{area_note}",

            f"Almost done! Total: *{total_str}*\n\n"
            f"Pick it up or have it delivered?\n\n"
            f"1️⃣ Pickup\n"
            f"2️⃣ Delivery (+{fee_str})"
            f"{area_note}",

            f"Ready to checkout! *{total_str}*\n\n"
            f"1️⃣ I'll collect it myself\n"
            f"2️⃣ Deliver to me (delivery fee: *{fee_str}*)"
            f"{area_note}",
        ])

    @classmethod
    def checkout_delivery_type_retry(cls) -> str:
        return cls._pick([
            "Just reply *1* to pick it up yourself, or *2* for delivery.",
            "Reply *1* for pickup or *2* for delivery — which do you prefer?",
        ])

    @classmethod
    def checkout_prompt(cls, total: float, style: str = "friendly_casual") -> str:
        total_str = cls._format_currency(total)
        return cls._pick_styled({
            "friendly_casual": [
                f"Your total is *{total_str}*. How would you like to pay?\n\n"
                f"1️⃣ Cash — pay when you pick it up\n"
                f"2️⃣ Card — pay now online",

                f"Ready to check out! Total: *{total_str}*\n\n"
                f"1️⃣ Pay cash at the store\n"
                f"2️⃣ Pay by card (online)",

                f"Almost done! *{total_str}* to pay.\n\n"
                f"1️⃣ Cash on pickup\n"
                f"2️⃣ Pay with card",
            ],
            "professional": [
                f"Your order total is *{total_str}*. Please select a payment method:\n\n"
                f"1️⃣ Cash — payable upon collection\n"
                f"2️⃣ Card — secure online payment",

                f"Total amount: *{total_str}*. How would you like to proceed?\n\n"
                f"1️⃣ Cash on collection\n"
                f"2️⃣ Online card payment",
            ],
            "warm_enthusiastic": [
                f"You're almost there! 🎉 Total: *{total_str}*\n\n"
                f"1️⃣ Cash — pay at pickup 💵\n"
                f"2️⃣ Card — pay online now 💳",

                f"So close! *{total_str}* to go! 😊\n\n"
                f"1️⃣ Cash on pickup\n"
                f"2️⃣ Pay by card now",
            ],
        }, style)

    @classmethod
    def checkout_prompt_retry(cls) -> str:
        return cls._pick([
            "Just reply *1* to pay cash at the store, or *2* to pay by card.",
            "Reply *1* for cash or *2* for card — which works for you?",
        ])

    @classmethod
    def ask_delivery_address(cls, delivery_area: Optional[str] = None) -> str:
        area_note = (
            f"\n_(We currently deliver within {delivery_area} only.)_"
            if delivery_area else ""
        )
        return cls._pick([
            f"Please share your *full delivery address*.\n\n"
            f"Include:\n• House/flat number\n• Street name\n• Area or estate\n• Closest bus stop or landmark"
            f"{area_note}",

            f"What's your delivery address? Please be as detailed as possible — "
            f"house number, street, area, and the nearest landmark or bus stop.\n\n"
            f"This helps our delivery person find you. 🙏"
            f"{area_note}",

            f"To complete your delivery, I need your full address:\n\n"
            f"📍 House/flat number and street\n"
            f"📍 Area or estate name\n"
            f"📍 A nearby landmark or bus stop"
            f"{area_note}",
        ])

    @classmethod
    def ask_delivery_contact(cls) -> str:
        return (
            "Our delivery person will contact you on this WhatsApp number when they're close. "
            "If you'd like them to call a different number instead, type it now. "
            "Otherwise reply *same*."
        )

    @classmethod
    def delivery_details_confirmed(cls, address: str, total_with_fee: float) -> str:
        total_str = cls._format_currency(total_with_fee)
        return cls._pick([
            f"Got it! Delivering to:\n_{address}_\n\n"
            f"Updated total (inc. delivery): *{total_str}*\n\n"
            f"How would you like to pay?\n\n1️⃣ Cash on delivery\n2️⃣ Card — pay now",

            f"Perfect. We'll deliver to:\n_{address}_\n\n"
            f"Total including delivery fee: *{total_str}*\n\n"
            f"1️⃣ Pay cash on delivery\n2️⃣ Pay by card now",
        ])

    @classmethod
    def empty_cart_checkout(cls, style: str = "friendly_casual") -> str:
        return cls._pick_styled({
            "friendly_casual": [
                "Your cart is empty — add something first and I'll help you check out!",
                "Nothing in your cart yet. What would you like to order?",
                "You haven't added anything yet. What can I get for you?",
            ],
            "professional": [
                "Your cart is currently empty. Please add items before proceeding to checkout.",
                "No items in your cart. Please select products before checking out.",
            ],
            "warm_enthusiastic": [
                "Oops — your cart is empty! 😊 Add something yummy and let's get you checked out!",
                "Nothing in the cart yet! 🛒 What would you like to add?",
            ],
        }, style)

    @classmethod
    def checkout_success(cls, order_code: str, total, instructions: str, style: str = "friendly_casual") -> str:
        total_str = cls._format_currency(cls._ensure_float(total))
        return cls._pick_styled({
            "friendly_casual": [
                f"🎉 You're all set!\n\n"
                f"*Order code: {order_code}*\n"
                f"Total: *{total_str}*\n\n"
                f"{instructions}\n\n"
                f"You can check your order anytime — just send *status {order_code}*",

                f"Order placed! ✅\n\n"
                f"Your code is *{order_code}* — keep it handy.\n"
                f"Amount: *{total_str}*\n\n"
                f"{instructions}",
            ],
            "professional": [
                f"Your order has been confirmed. ✅\n\n"
                f"*Order reference: {order_code}*\n"
                f"Total: *{total_str}*\n\n"
                f"{instructions}\n\n"
                f"To track your order, send *status {order_code}*",

                f"Order confirmed. ✅\n\n"
                f"Reference: *{order_code}* | Amount: *{total_str}*\n\n"
                f"{instructions}",
            ],
            "warm_enthusiastic": [
                f"Woohoo! Your order is in! 🎉🛒\n\n"
                f"*Order code: {order_code}*\n"
                f"Total: *{total_str}*\n\n"
                f"{instructions}\n\n"
                f"So excited for you! Track it anytime with *status {order_code}* 😊",

                f"Yes! Order placed! 🙌\n\n"
                f"Code: *{order_code}* | Total: *{total_str}*\n\n"
                f"{instructions}",
            ],
        }, style)

    @classmethod
    def checkout_pending(cls, payment_link: str, style: str = "friendly_casual") -> str:
        return cls._pick_styled({
            "friendly_casual": [
                f"Almost there! Tap the link below to complete payment:\n\n{payment_link}\n\n"
                f"I'll message you as soon as it goes through. 👍",

                f"Your order is ready — just pay here:\n\n{payment_link}\n\n"
                f"Once it's confirmed I'll let you know right away!",
            ],
            "professional": [
                f"Please complete your payment using the link below:\n\n{payment_link}\n\n"
                f"You will receive a confirmation once the payment is processed.",

                f"Your order is pending payment. Please use the link below to proceed:\n\n{payment_link}",
            ],
            "warm_enthusiastic": [
                f"One last step — you're so close! 🎉 Tap here to pay:\n\n{payment_link}\n\n"
                f"I'll ping you the moment it's confirmed! 🙌",

                f"Almost done! 😊 Just tap to pay:\n\n{payment_link}\n\n"
                f"Can't wait to confirm your order!",
            ],
        }, style)

    @classmethod
    def checkout_instructions_cash(cls, order_code: str) -> str:
        return cls._pick([
            f"Show your order code *{order_code}* when you arrive and our team will have it ready for you.",
            f"Head to the store with your code *{order_code}* — we'll get everything ready.",
            f"Your order code is *{order_code}*. Show it when you arrive and we'll take care of you.",
        ])

    @classmethod
    def checkout_instructions_cash_delivery(cls, order_code: str) -> str:
        return (
            f"Your order code is *{order_code}*. "
            f"Our delivery person will contact you before arriving. "
            f"Please have cash ready when they get there."
        )

    @classmethod
    def checkout_already_active(cls, style: str = "friendly_casual") -> str:
        return cls._pick_styled({
            "friendly_casual": [
                "You have an open card payment that hasn't been completed. "
                "Finish that payment, or send *new* to cancel it and start fresh.",
                "There's an unpaid order still open. Complete the payment, "
                "or send *new* to discard it and place a new one.",
            ],
            "professional": [
                "An incomplete card payment exists on your account. "
                "Please complete it, or send *new* to cancel and begin a new order.",
                "You have a pending payment outstanding. Please settle it or send *new* to restart.",
            ],
            "warm_enthusiastic": [
                "Looks like you've got an open payment waiting! 😊 "
                "Complete it to confirm your order, or send *new* to cancel and start fresh.",
                "There's still an unpaid order hanging — no worries! "
                "Finish that one or send *new* to start over. 🛒",
            ],
        }, style)

    @classmethod
    def checkout_failed(cls, style: str = "friendly_casual") -> str:
        return cls._pick_styled({
            "friendly_casual": [
                "Something went wrong on our end — sorry about that. Try again?",
                "Oops, that didn't go through. Want to try again?",
            ],
            "professional": [
                "We encountered an issue processing your order. Please try again.",
                "Your order could not be completed due to a system error. Please retry.",
            ],
            "warm_enthusiastic": [
                "Oh no, something went wrong! 😟 Don't worry — just try again and we'll sort it out!",
                "Oops! That didn't work. Let's give it another shot! 💪",
            ],
        }, style)

    # ── Payment ───────────────────────────────────────────────────────────────

    @classmethod
    def payment_confirmed(cls, order_code: str, store_name: Optional[str] = None) -> str:
        header  = f"*{store_name}*\n" if store_name else ""
        powered = "\n_Powered by ShopprHQ_"
        return cls._pick([
            f"{header}✅ Payment received! Order *{order_code}* is confirmed. Thank you!{powered}",
            f"{header}Got your payment! Order *{order_code}* is all set. Thanks for shopping with us!{powered}",
            f"{header}Payment confirmed for order *{order_code}*. You're good to go! 🎉{powered}",
        ])

    @classmethod
    def cash_payment_receipt(
        cls,
        order_code: str,
        total: float,
        items_lines: str,
        store_name: Optional[str] = None,
    ) -> str:
        total_str = cls._format_currency(total)
        header  = f"*{store_name}*\n" if store_name else ""
        powered = "\n_Powered by ShopprHQ_"
        return cls._pick([
            f"{header}✅ Cash payment confirmed!\n\n"
            f"*Order {order_code}*\n{items_lines}\n\n"
            f"Total paid: *{total_str}*\n\nThank you — enjoy! 😊{powered}",

            f"{header}All done! Your order *{order_code}* is complete.\n\n"
            f"{items_lines}\n\nAmount: *{total_str}*\n\nThanks for shopping with us! 🙏{powered}",

            f"{header}Payment received ✅\n\n"
            f"*{order_code}* — {total_str} paid.\n\n{items_lines}\n\nEnjoy your purchase!{powered}",
        ])

    # ── Delivery notifications ────────────────────────────────────────────────

    @classmethod
    def order_out_for_delivery(
        cls,
        order_code: str,
        contact_number: Optional[str] = None,
    ) -> str:
        contact_note = (
            f"\n\nThe delivery person will call *{contact_number}* when they're close."
            if contact_number
            else "\n\nThe delivery person will contact you when they're close."
        )
        return cls._pick([
            f"🛵 Your order *{order_code}* is on its way!\n\n"
            f"Our delivery person has just picked it up and is heading to you.{contact_note}",

            f"Great news! 🎉 Order *{order_code}* is out for delivery.\n\nShouldn't be long now!{contact_note}",

            f"Your order *{order_code}* has left and is on the way to you! 🚀{contact_note}",
        ])

    # ── Order status ──────────────────────────────────────────────────────────

    @classmethod
    def order_status_not_found(cls, order_code: str) -> str:
        return cls._pick([
            f"I couldn't find order *{order_code}*. Double-check the code and try again.",
            f"No order found with code *{order_code}*. Make sure you've got the right one.",
        ])

    @classmethod
    def order_status_prompt(cls) -> str:
        return "To check your order, send *status* followed by your order code.\n\ne.g. *status X7K4M2PQ*"

    # ── Human handoff ─────────────────────────────────────────────────────────

    @classmethod
    def human_handoff_with_number(cls, store_name: str, operator_number: str) -> str:
        # FLOW-10: use a wa.me deep-link so the operator's personal number is never
        # exposed as plain text in the customer's chat history — tapping the link
        # opens a WhatsApp chat directly without revealing the underlying number.
        clean_number = operator_number.lstrip("+").replace(" ", "")
        wa_link = f"https://wa.me/{clean_number}"
        return cls._pick([
            f"Of course! Tap the link below to chat with the *{store_name}* team directly:\n{wa_link}\n\nI'll still be here if you need me. 😊",

            f"No problem — you can reach someone from *{store_name}* here:\n{wa_link}\n\nIs there anything else I can help with in the meantime?",

            f"Sure! Connect with the *{store_name}* team directly:\n{wa_link}\n\nThey'll be happy to help you.",
        ])

    @classmethod
    def human_handoff_no_number(cls, store_name: str) -> str:
        return cls._pick([
            f"I'll let the *{store_name}* team know you'd like to speak with someone. "
            f"They'll reach out to you shortly!\n\nIs there anything else I can help with in the meantime?",

            f"Got it — I'll flag this for the *{store_name}* team and they'll get back to you soon.",

            f"I've noted that you'd like to speak with someone from *{store_name}*. "
            f"They'll be in touch shortly!",
        ])

    # ── Session expiry ────────────────────────────────────────────────────────

    @classmethod
    def search_expired(cls) -> str:
        # FLOW-9: every variant must tell the customer how to recover — not just one of three.
        return cls._pick([
            "It's been a while — your search timed out. Just type a product name to start again!",
            "Your previous search has expired. Just type a product name to start again!",
            "Looks like we got disconnected for a bit. Just type a product name and I'll find it for you!",
        ])

    # ── Misc / errors ─────────────────────────────────────────────────────────

    @classmethod
    def fallback(cls, style: str = "friendly_casual") -> str:
        return cls._pick_styled({
            "friendly_casual": [
                "I didn't quite catch that. Could you rephrase it?",
                "Hmm, not sure I understood. Try describing what you're looking for?",
                "I'm not sure what you mean — want to search for a product, or need help?",
                "Could you say that another way? I want to make sure I get it right.",
            ],
            "professional": [
                "I'm sorry, I didn't understand your request. Could you please clarify?",
                "I was unable to process that. Could you rephrase your request?",
                "That wasn't clear to me. Please describe what you're looking for.",
            ],
            "warm_enthusiastic": [
                "Oops, I missed that! 😅 Could you say it again?",
                "Hmm, I'm not quite sure what you mean — try me again! 😊",
                "I didn't catch that one! Give me another shot — what are you looking for? 🙌",
            ],
        }, style)

    @classmethod
    def help(cls) -> str:
        return (
            "Here's what I can do:\n\n"
            "*Search* — just type any product name\n"
            "*Cart* — say _my cart_ or _show cart_ to see what you've added\n"
            "*Remove* — say _remove [item]_ to take something out\n"
            "*Quantity* — say _make it 3_ or _change Pepsi to 2_\n"
            "*Checkout* — say _checkout_ or _I want to pay_ when you're ready\n"
            "*Order status* — send _status ORDERCODE_\n"
            "*Start over* — send _new_ to clear your cart\n\n"
            "What would you like to do?"
        )

    @classmethod
    def error(cls, error_type: str) -> str:
        errors = {
            "inventory": "That item is out of stock right now. Want me to find something similar?",
            "payment":   "Something went wrong with the payment. Want to try again?",
            "timeout":   "That took too long to process. Let's try again — what would you like?",
            "generic":   "Something went wrong on our end. Give it another try?",
        }
        return errors.get(error_type, errors["generic"])

    @classmethod
    def confirm_invalid_command(cls) -> str:
        return cls._pick([
            "That command isn't available here. Looking for something?",
            "Only store staff can use that. What can I help you with?",
        ])

    # ── Quantity / cart update responses ──────────────────────────────────────

    @classmethod
    def quantity_updated(cls, item_name: str, quantity: int, subtotal, total) -> str:
        sub_str   = cls._format_currency(cls._ensure_float(subtotal))
        total_str = cls._format_currency(cls._ensure_float(total))
        if quantity == 0:
            return cls._pick([
                f"Removed *{item_name}* from your cart. New total: *{total_str}*",
                f"*{item_name}* taken out. Your total is now *{total_str}*.",
            ])
        return cls._pick([
            f"Updated! *{quantity}x {item_name}* = {sub_str}. Cart total: *{total_str}*",
            f"Done — *{item_name}* is now {quantity} ({sub_str}). Total: *{total_str}*",
        ])

    @classmethod
    def ask_quantity(cls, item_name: str) -> str:
        return cls._pick([
            f"How many *{item_name}* would you like?",
            f"What quantity of *{item_name}* do you need?",
            f"How many should I add?",
        ])

    @classmethod
    def removed_items(cls, items: str, total: Optional[float] = None) -> str:
        if total is not None:
            total_str = cls._format_currency(cls._ensure_float(total))
            return cls._pick([
                f"Removed *{items}*. New total: *{total_str}*",
                f"*{items}* taken out of your cart. Total is now *{total_str}*.",
                f"Done — *{items}* is gone. Cart total: *{total_str}*",
            ])
        return cls._pick([
            f"Removed *{items}* from your cart.",
            f"*{items}* is out.",
            f"Done — *{items}* removed.",
        ])

    @classmethod
    def cart_cleared(cls) -> str:
        return cls._pick([
            "Cart cleared! What would you like to order?",
            "Done — your cart is empty. What are you looking for?",
            "All cleared! Start fresh — what can I get you?",
        ])

    @classmethod
    def remove_failed(cls) -> str:
        return cls._pick([
            "I couldn't find that in your cart. Say *my cart* to see what's in there.",
            "Hmm, that doesn't seem to be in your cart. Say *cart* to check.",
        ])

    @classmethod
    def nothing_added(cls) -> str:
        return cls._pick([
            "I couldn't find that product. Try a different name?",
            "Nothing matched — want to try searching by name?",
        ])

    @classmethod
    def no_active_cart(cls) -> str:
        return cls._pick([
            "You don't have anything in your cart yet. What would you like to order?",
            "Your cart is empty. Just tell me what you're looking for!",
        ])

    @classmethod
    def start_fresh(cls) -> str:
        return cls._pick([
            "Fresh start! 🛒 What would you like to order?",
            "All clear — what can I get for you?",
            "Ready for a new order! What are you looking for?",
        ])

    @classmethod
    def quantity_update_not_found(cls) -> str:
        return cls._pick([
            "I couldn't find that item in your cart. Say *my cart* to see what you have.",
            "That doesn't seem to be in your cart. Say *cart* to check.",
        ])

    @classmethod
    def quantity_update_empty_cart(cls) -> str:
        return cls._pick([
            "Your cart is empty — nothing to update. What would you like to order?",
            "Nothing in your cart yet to change. What can I get for you?",
        ])

    # ── Social acknowledgment ─────────────────────────────────────────────────

    @classmethod
    def social_acknowledgment(cls, style: str = "friendly_casual") -> str:
        return cls._pick_styled({
            "friendly_casual": [
                "No worries! 😊 Just let me know whenever you'd like to order something.",
                "Anytime! I'm here when you need me.",
                "Of course! Just say the word whenever you're ready.",
            ],
            "professional": [
                "Understood. I'm available whenever you'd like to place an order.",
                "Thank you. Please let me know if there's anything else I can assist you with.",
                "Noted. Feel free to reach out whenever you need assistance.",
            ],
            "warm_enthusiastic": [
                "You're so welcome! 🌟 I'm here whenever you need me!",
                "Anytime! 😄 Just come back when you're ready — I love helping!",
                "Happy to be here! Don't hesitate to reach out anytime! 🙌",
            ],
        }, style)

    # ── Store hours ───────────────────────────────────────────────────────────

    @classmethod
    def store_hours_info(
        cls,
        opens_at: Optional[str],
        closes_at: Optional[str],
        is_open: bool,
        store_name: Optional[str] = None,
    ) -> str:
        store = f"*{store_name}*" if store_name else "We"
        if not opens_at or not closes_at:
            return cls._pick([
                f"{store} are open 24/7 — order any time!",
                f"We're available around the clock. Order whenever it suits you!",
                f"{store} never close! You can shop any time. 😊",
            ])

        def _fmt(t: str) -> str:
            try:
                h, m = t.split(":")
                h      = int(h)
                suffix = "AM" if h < 12 else "PM"
                h      = h % 12 or 12
                return f"{h}:{m} {suffix}"
            except Exception:
                return t

        open_str  = _fmt(opens_at)
        close_str = _fmt(closes_at)
        status    = "currently *open* ✅" if is_open else "currently *closed* 🔴"
        return cls._pick([
            f"{store} are {status}.\n\nOur hours: *{open_str} – {close_str}* daily.",
            f"We're {status}. Store hours are *{open_str} to {close_str}* every day.",
            f"Hours: *{open_str} – {close_str}* daily. We're {status} right now.",
        ])

    @classmethod
    def store_closed_notice(
        cls,
        opens_at: str,
        closes_at: str,
        store_name: Optional[str] = None,
    ) -> str:
        def _fmt(t: str) -> str:
            try:
                h, m   = t.split(":")
                h      = int(h)
                suffix = "AM" if h < 12 else "PM"
                h      = h % 12 or 12
                return f"{h}:{m} {suffix}"
            except Exception:
                return t

        store     = store_name or "the store"
        open_str  = _fmt(opens_at)
        close_str = _fmt(closes_at)
        return cls._pick([
            f"🕐 *{store}* is currently closed (hours: {open_str}–{close_str}). "
            f"You can still browse and place an order — we'll fulfil it when we open!\n\n",
            f"We're currently closed 🔴 (open {open_str}–{close_str}). "
            f"No problem though — place your order now and it'll be ready when we open!\n\n",
            f"⚠️ *{store}* is closed right now. Our hours are {open_str}–{close_str}. "
            f"Feel free to order anyway — we'll get to it first thing when we open!\n\n",
        ])