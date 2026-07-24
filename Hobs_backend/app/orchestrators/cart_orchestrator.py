# app/orchestrators/cart_orchestrator.py

from typing import Dict, Any, List, Optional
import logging

from app.schemas.cart import CartItemSchema
from app.conversation.humanizer import Humanizer
from app.orchestrators.context import ConversationContext

logger = logging.getLogger(__name__)

FUZZY_MATCH_THRESHOLD = 65.0


class CartOrchestrator:

    def __init__(self, context: ConversationContext):
        self.ctx          = context
        self.cart_service = context.cart_service
        self.matcher      = context.matcher
        self.memory       = context.memory
        self.tenant       = context.tenant

        self.merchant_id = str(context.tenant.merchant_id)
        self.client_id   = str(context.tenant.client_id)
        self.style       = context.tenant.persona_style
        self.user_id     = context.user_phone

    # ==========================================================
    # ADD TO CART
    # ==========================================================

    async def add_to_cart(self, products: List[Dict[str, Any]]) -> str:

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

        added_items = []
        last_added_name = None

        for product in products:
            product_id   = product.get("product_id")
            product_name = product.get("name")
            quantity     = product.get("quantity", 1)

            if product_id:
                item = CartItemSchema(
                    product_id=product_id,
                    quantity=quantity,
                    price_at_add=product.get("price", 0),
                )
                await self.cart_service.add_item(
                    merchant_id=self.merchant_id,
                    client_id=self.client_id,
                    cart_id=cart.id,
                    item=item,
                )
                added_items.append(f"{quantity}x {product_name or 'item'}")
                last_added_name = product_name or "item"
                continue

            if product_name:
                matches = await self.matcher.search(
                    query=product_name,
                    merchant_id=self.merchant_id,
                    client_id=self.client_id,
                    limit=3,
                )

                if not matches:
                    return Humanizer.no_results(product_name, self.style)

                best = matches[0]

                if best.score < FUZZY_MATCH_THRESHOLD:
                    # Low confidence — show options conversationally
                    await self.memory.set_choices([
                        {
                            "product_id": str(m.product_id),
                            "name":       m.name,
                            "price":      float(m.price) if m.price else 0.0,
                        }
                        for m in matches[:3]
                    ])
                    await self.memory.set("pending_selection_qty", quantity)
                    await self.memory.set_mode("selecting")
                    return Humanizer.present_choices_conversational(
                        choices=matches[:3],
                        query=product_name,
                        style=self.style,
                    )

                item = CartItemSchema(
                    product_id=best.product_id,
                    quantity=quantity,
                    price_at_add=best.price or 0.0,
                )
                await self.cart_service.add_item(
                    merchant_id=self.merchant_id,
                    client_id=self.client_id,
                    cart_id=cart.id,
                    item=item,
                )
                added_items.append(f"{quantity}x {best.name}")
                last_added_name = best.name

        if not added_items:
            return Humanizer.nothing_added()

        # Use flush + _build_summary on the live cart object to get the correct
        # total within the open transaction (avoids stale reads via get_cart_summary).
        # NOTE: get_active_cart now uses populate_existing() under the hood
        # (see cart_service.py), so this is guaranteed to reflect the items
        # just added, including on the very first item in a brand-new cart.
        await self.ctx.db.flush()
        updated_cart = await self.cart_service.get_active_cart(
            merchant_id=self.merchant_id,
            client_id=self.client_id,
            user_id=self.user_id,
        )
        summary = self.cart_service._build_summary(updated_cart)

        await self.memory.set_mode("shopping")
        await self.memory.clear_choices()
        if last_added_name:
            await self.memory.set("last_added_product", last_added_name)

        return Humanizer.added_to_cart(
            ", ".join(added_items),
            summary["item_count"],
            summary["total"],
            style=self.style,
        )

    # ==========================================================
    # UPDATE QUANTITY
    # ==========================================================

    async def update_quantity(self, quantity_updates: List[Dict[str, Any]]) -> str:

        if not quantity_updates:
            return Humanizer.quantity_update_empty_cart()

        cart = await self.cart_service.get_active_cart(
            merchant_id=self.merchant_id,
            client_id=self.client_id,
            user_id=self.user_id,
        )

        if not cart or not cart.items:
            return Humanizer.quantity_update_empty_cart()

        updated = []
        failed  = []

        for update in quantity_updates:
            name       = update.get("name", "")
            quantity   = update.get("quantity", 1)
            item_index = update.get("item_index")

            if quantity < 0:
                failed.append(name or "item")
                continue

            matched_item = None

            # Match by explicit index
            if item_index is not None:
                try:
                    matched_item = cart.items[int(item_index)]
                except (IndexError, TypeError, ValueError):
                    matched_item = None

            # Match by name
            if not matched_item and name:
                name_lower = name.lower()
                for cart_item in cart.items:
                    item_name = ""
                    if hasattr(cart_item, "product") and cart_item.product:
                        item_name = cart_item.product.name.lower()
                    if name_lower in item_name or item_name in name_lower:
                        matched_item = cart_item
                        break

            # Single-item cart fallback - bare quantity, no name, unambiguous
            if not matched_item and not name and len(cart.items) == 1:
                matched_item = cart.items[0]

            # Last-added product fallback - bare quantity, multiple items in cart.
            # FIX: previously applied silently. Now confirms with the customer first
            # when the cart has 2+ items so "make it 3" never mutates the wrong item.
            # Single-item carts are already handled above - this only fires for 2+ items.
            if not matched_item and not name:
                last_added = await self.memory.get("last_added_product")
                if last_added:
                    last_lower = last_added.lower()
                    for cart_item in cart.items:
                        item_name = ""
                        if hasattr(cart_item, "product") and cart_item.product:
                            item_name = cart_item.product.name.lower()
                        if last_lower in item_name or item_name in last_lower:
                            if len(cart.items) > 1:
                                # Multiple items - confirm before applying
                                _display = (
                                    cart_item.product.name
                                    if hasattr(cart_item, "product") and cart_item.product
                                    else last_added
                                )
                                await self.memory.set("pending_qty_update", {
                                    "product_id": str(cart_item.product_id),
                                    "name": _display,
                                    "quantity": quantity,
                                })
                                await self.memory.set_mode("confirming_qty_update")
                                from app.conversation.humanizer import Humanizer as _H
                                return _H._pick([
                                    f"Just to confirm - updating *{_display}* to {quantity}? Reply *yes* or *no*.",
                                    f"Updating *{_display}* to {quantity} - is that right? Reply *yes* to confirm.",
                                    f"Did you mean *{_display}* x {quantity}? Reply *yes* to update or *no* to cancel.",
                                ])
                            else:
                                matched_item = cart_item
                            break

            if not matched_item:
                failed.append(name or "item")
                continue

            try:
                product_id   = str(matched_item.product_id)
                product_name = (
                    matched_item.product.name
                    if hasattr(matched_item, "product") and matched_item.product
                    else name or "item"
                )

                await self.cart_service.set_item_quantity(
                    merchant_id=self.merchant_id,
                    client_id=self.client_id,
                    cart_id=cart.id,
                    product_id=product_id,
                    quantity=quantity,
                )

                if quantity == 0:
                    updated.append(f"removed {product_name}")
                else:
                    updated.append(f"{product_name} → {quantity}")

            except Exception as e:
                logger.error("update_quantity failed for %s: %s", name, e)
                failed.append(name or "item")

        summary = await self.cart_service.get_cart_summary(
            merchant_id=self.merchant_id,
            client_id=self.client_id,
            user_id=self.user_id,
        )

        if not updated:
            return Humanizer.quantity_update_not_found()

        lines = ["Updated! ✅"]
        for u in updated:
            lines.append(f"  • {u}")
        if failed:
            lines.append(f"\nCouldn't find: {', '.join(failed)}")
        if summary["has_items"]:
            lines.append(f"\nCart total: *{Humanizer._format_currency(summary['total'])}*")
        else:
            lines.append("\nYour cart is now empty.")

        return "\n".join(lines)

    # ==========================================================
    # VIEW CART
    # ==========================================================

    # ==========================================================
    # HANDLE QUANTITY UPDATE CONFIRMATION (mode: confirming_qty_update)
    # FIX: handles the yes/no reply after we asked "updating X to N - right?"
    # Only fires when update_quantity detected an ambiguous bare-quantity message
    # on a multi-item cart and stored the pending update in memory.
    # ==========================================================

    async def handle_qty_update_confirm(self, user_input: str) -> str:
        pending = await self.memory.get("pending_qty_update")

        if not pending:
            await self.memory.set_mode("shopping")
            return Humanizer.quantity_update_not_found()

        text = user_input.strip().lower()

        _CONFIRM = {"yes", "yeah", "yep", "yup", "ok", "okay", "sure",
                    "confirm", "go ahead", "proceed", "oya", "do it", "yes please"}
        _CANCEL  = {"no", "nah", "nope", "cancel", "nevermind", "never mind",
                    "stop", "forget it", "no thanks"}

        await self.memory.delete("pending_qty_update")
        await self.memory.set_mode("shopping")

        if text in _CANCEL:
            return Humanizer._pick([
                "No problem - nothing changed. What else can I help with?",
                "Got it - cart left as is. Anything else?",
            ])

        if text not in _CONFIRM:
            # Not a clear yes or no - treat as cancel and let them rephrase
            return Humanizer._pick([
                "I'll leave that unchanged. Just say what you'd like to update.",
                "No changes made. Let me know what you need!",
            ])

        # Confirmed - apply the update
        product_id = pending.get("product_id")
        name       = pending.get("name", "item")
        quantity   = pending.get("quantity", 1)

        cart = await self.cart_service.get_active_cart(
            merchant_id=self.merchant_id,
            client_id=self.client_id,
            user_id=self.user_id,
        )
        if not cart:
            return Humanizer.quantity_update_empty_cart()

        try:
            await self.cart_service.set_item_quantity(
                merchant_id=self.merchant_id,
                client_id=self.client_id,
                cart_id=cart.id,
                product_id=product_id,
                quantity=quantity,
            )
        except Exception as e:
            logger.error("handle_qty_update_confirm failed for %s: %s", name, e)
            return Humanizer.error("generic")

        summary = await self.cart_service.get_cart_summary(
            merchant_id=self.merchant_id,
            client_id=self.client_id,
            user_id=self.user_id,
        )
        total_str = Humanizer._format_currency(summary["total"])

        if quantity == 0:
            return Humanizer._pick([
                f"Removed *{name}*. Cart total: *{total_str}*",
                f"*{name}* taken out. Total: *{total_str}*",
            ])
        return Humanizer._pick([
            f"Done! *{name}* updated to {quantity}. Cart total: *{total_str}*",
            f"*{name}* is now {quantity}. Total: *{total_str}*",
        ])

    async def view_cart(self) -> str:

        summary = await self.cart_service.get_cart_summary(
            merchant_id=self.merchant_id,
            client_id=self.client_id,
            user_id=self.user_id,
        )

        if not summary["has_items"]:
            return Humanizer.empty_cart()

        lines = ["Here's your cart:\n"]
        for i, item in enumerate(summary["items"], 1):
            lines.append(
                f"{i}. {item['product_name']}\n"
                f"   {item['quantity']} × {Humanizer._format_currency(item['price'])} "
                f"= {Humanizer._format_currency(item['subtotal'])}"
            )
        lines.append(f"\n*Total: {Humanizer._format_currency(summary['total'])}*")
        lines.append("\nReady to order? Just say *checkout* — or keep adding items.")

        return "\n".join(lines)

    # ==========================================================
    # REMOVE ITEM
    # ==========================================================

    async def remove_item(self, products: List[Dict[str, Any]]) -> str:

        cart = await self.cart_service.get_active_cart(
            merchant_id=self.merchant_id,
            client_id=self.client_id,
            user_id=self.user_id,
        )

        if not cart:
            return Humanizer.no_active_cart()

        removed = []

        for product in products:
            product_id   = product.get("product_id")
            product_name = product.get("name", "")

            if not product_id and product_name:
                name_lower = product_name.lower()
                for cart_item in (cart.items or []):
                    item_name = ""
                    if hasattr(cart_item, "product") and cart_item.product:
                        item_name = cart_item.product.name.lower()
                    if name_lower in item_name or item_name in name_lower:
                        product_id = str(cart_item.product_id)
                        break

            if not product_id:
                continue
            try:
                await self.cart_service.remove_item(
                    merchant_id=self.merchant_id,
                    client_id=self.client_id,
                    cart_id=cart.id,
                    product_id=product_id,
                )
                removed.append(product_name or product_id)
            except Exception:
                continue

        if not removed:
            return Humanizer.remove_failed()

        summary = await self.cart_service.get_cart_summary(
            merchant_id=self.merchant_id,
            client_id=self.client_id,
            user_id=self.user_id,
        )

        display_name = ", ".join(removed) if removed else "item"
        return Humanizer.removed_items(
            display_name,
            summary["total"] if summary["has_items"] else None,
        )

    # ==========================================================
    # CLEAR CART
    # ==========================================================

    async def clear_cart(self) -> str:

        cart = await self.cart_service.get_active_cart(
            merchant_id=self.merchant_id,
            client_id=self.client_id,
            user_id=self.user_id,
        )

        if not cart:
            return Humanizer.empty_cart()

        await self.cart_service.clear_cart(
            merchant_id=self.merchant_id,
            client_id=self.client_id,
            cart_id=cart.id,
        )

        await self.memory.set_mode("idle")
        await self.memory.delete("last_added_product")
        return Humanizer.cart_cleared()

    # ==========================================================
    # START NEW ORDER
    # ==========================================================

    async def start_new_order(self) -> str:
        # FLOW-4: if the cart already has items, ask for explicit confirmation
        # before wiping it.  A customer who says "start over" with a ₦15k cart
        # loaded deserves a safety prompt — not an instant wipe.
        current_mode = await self.memory.get_mode()

        if current_mode == "confirming_new_order":
            # Customer has already seen the warning and is now confirming — proceed.
            await self.memory.set_mode("idle")
            await self.memory.clear_choices()
            await self.memory.delete("last_added_product")
            await self.cart_service.create_cart(
                merchant_id=self.merchant_id,
                client_id=self.client_id,
                user_id=self.user_id,
            )
            return Humanizer.start_fresh()

        # Check if there are items worth protecting
        summary = await self.cart_service.get_cart_summary(
            merchant_id=self.merchant_id,
            client_id=self.client_id,
            user_id=self.user_id,
        )

        if summary.get("has_items"):
            total_str = Humanizer._format_currency(summary["total"])
            await self.memory.set_mode("confirming_new_order")
            return Humanizer._pick([
                f"You have items in your cart worth *{total_str}*. "                f"Starting over will clear everything.\n\n"                f"Reply *yes* to start fresh, or keep shopping.",

                f"Your current cart total is *{total_str}*. "                f"Are you sure you want to clear it and start a new order?\n\n"                f"Reply *yes* to confirm, or just continue shopping.",
            ])

        # Cart is already empty — just reset cleanly
        await self.memory.set_mode("idle")
        await self.memory.clear_choices()
        await self.memory.delete("last_added_product")
        await self.cart_service.create_cart(
            merchant_id=self.merchant_id,
            client_id=self.client_id,
            user_id=self.user_id,
        )
        return Humanizer.start_fresh()

    # ==========================================================
    # REPEAT LAST ORDER
    # ==========================================================

    async def repeat_last_order(self) -> str:
        last_order = await self.memory.get("pending_repeat_order")

        if not last_order or not last_order.get("items"):
            return await self.start_new_order()

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

        added   = []
        skipped = []

        for item in last_order["items"]:
            name = item.get("name", "")
            qty  = max(1, int(item.get("qty", 1)))

            matches = await self.matcher.search(
                query=name,
                merchant_id=self.merchant_id,
                client_id=self.client_id,
                limit=1,
            )

            if not matches or matches[0].score < 70:
                skipped.append(name)
                continue

            best = matches[0]

            try:
                # Re-fetch the current price from the DB so repeat orders
                # always use the live price, not the stale fuzzy-match cache.
                from sqlalchemy import select as _sa_select
                from app.models.product import Product as _Product
                _prod_res = await self.ctx.db.execute(
                    _sa_select(_Product).where(_Product.id == best.product_id)
                )
                _prod = _prod_res.scalar_one_or_none()
                current_price = float(_prod.price) if _prod and _prod.price else (best.price or 0.0)

                await self.cart_service.add_item(
                    merchant_id=self.merchant_id,
                    client_id=self.client_id,
                    cart_id=cart.id,
                    item=CartItemSchema(
                        product_id=best.product_id,
                        quantity=qty,
                        price_at_add=current_price,
                    ),
                )
                added.append(f"{qty}x {best.name}")
            except Exception:
                skipped.append(name)

        await self.memory.delete("pending_repeat_order")
        await self.memory.set_mode("shopping")

        if not added:
            return (
                "Sorry, none of the items from your last order are available right now. "
                "What would you like instead?"
            )

        summary = await self.cart_service.get_cart_summary(
            merchant_id=self.merchant_id,
            client_id=self.client_id,
            user_id=self.user_id,
        )
        total_str = Humanizer._format_currency(summary["total"])

        msg = "Done! Added to your cart:\n" + "\n".join(f"  • {a}" for a in added)
        if skipped:
            msg += f"\n\n_(Some items weren't available: {', '.join(skipped)})_"
        msg += f"\n\nCart total: *{total_str}*\n\nSend *checkout* when you're ready, or keep adding items."
        return msg