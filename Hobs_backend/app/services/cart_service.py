import logging
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.cart import Cart, CartItem
from app.models.product import Product
from app.schemas.cart import CartItemSchema
from app.db.transaction import flush_only, transactional

logger = logging.getLogger(__name__)


def generate_uuid() -> str:
    return str(uuid4())


class CartService:
    """
    Cart lifecycle manager.

    RULES:
    - Cart NEVER touches inventory
    - Cart only records user intent
    - Checkout owns stock mutation
    - ALL operations are tenant-scoped
    - Products are eagerly loaded for display
    """

    def __init__(self, db: AsyncSession):
        if not db:
            raise ValueError("AsyncSession must be provided")
        self.db = db

    # -------------------------------------------------
    # INTERNAL: FETCH CART WITH TENANT SAFETY
    # -------------------------------------------------
    async def _get_cart_for_update(
        self,
        merchant_id: str,
        client_id: str,
        cart_id: str,
    ) -> Cart:
        """
        Get cart by ID with tenant safety.
        NO LOCKS, NO JOINS, just the cart.
        """
        result = await self.db.execute(
            select(Cart)
            .where(
                Cart.id == cart_id,
                Cart.merchant_id == merchant_id,
                Cart.client_id == client_id,
            )
        )

        cart = result.scalar_one_or_none()

        if not cart:
            raise ValueError("Cart not found")

        return cart

    # -------------------------------------------------
    # INTERNAL: FETCH CART READ-ONLY WITH PRODUCTS
    # -------------------------------------------------
    async def _get_cart_readonly(
        self,
        merchant_id: str,
        client_id: str,
        cart_id: str,
    ) -> Cart | None:
        """
        Get cart by ID with tenant safety (read-only).
        Eager loads items and their associated products.
        No lock, for returning fresh state after mutations.

        ROOT-CAUSE FIX: this method is called right after a mutation
        (e.g. add_item) specifically to return "fresh state" within the
        same transaction. But without populate_existing(), SQLAlchemy's
        identity map will happily hand back the SAME already-loaded Cart
        object from an earlier read in this session/transaction — including
        whatever `items` collection was cached on it at that time.

        Concretely, on the very first item added to a brand-new cart:
          1. create_cart() flushes the new Cart, then calls this method.
             At that point items=[] in the DB, so SQLAlchemy loads and
             caches cart.items = [] on the identity-mapped object.
          2. add_item() adds the new CartItem row and flushes, then calls
             this method again. The query re-runs, but SQLAlchemy sees the
             Cart with this primary key is already in the identity map
             with `items` already loaded -> it reuses the *stale* empty
             list instead of re-querying it, even though selectinload is
             specified.
          3. _build_summary() then sums over that stale empty list and
             reports a total of 0.0 -> the customer sees "Cart total: ₦0.00"
             on their first item, even though the row really was inserted.
          4. On the second add, the collection has since been populated at
             least once, so this no longer reproduces -> totals are correct
             from the 2nd item onward. This matches what was observed.

        populate_existing() tells SQLAlchemy to overwrite already-loaded
        attributes/relationships on identity-mapped objects with what the
        query actually returns, instead of trusting the cached state. That
        makes this method genuinely "fresh" as its docstring already claims.
        """
        result = await self.db.execute(
            select(Cart)
            .where(
                Cart.id == cart_id,
                Cart.merchant_id == merchant_id,
                Cart.client_id == client_id,
            )
            .options(
                selectinload(Cart.items).selectinload(CartItem.product)
            )
            .execution_options(populate_existing=True)
        )

        return result.scalars().first()

    # -----------------------------
    # GET ACTIVE CART (WITH PRODUCTS)
    # -----------------------------
    async def get_active_cart(
        self,
        merchant_id: str,
        client_id: str,
        user_id: str,
    ) -> Cart | None:
        """
        Get the active (non-checked-out) cart for a user.
        Eager loads items and their associated products for display.
        Returns None if no active cart exists.
        Tenant safety is enforced through WHERE clause.

        ROOT-CAUSE FIX: this is called multiple times per request, both
        before and after mutations, within the same transaction/session.
        Without populate_existing(), a Cart object already sitting in the
        session's identity map (e.g. loaded once with an empty `items`
        collection right after creation) gets handed back unchanged on
        later calls instead of being refreshed against the DB — even
        though items were added to it in the meantime. See
        _get_cart_readonly for the full explanation; the same fix applies
        here for the same reason.
        """
        result = await self.db.execute(
            select(Cart)
            .where(
                Cart.merchant_id == merchant_id,
                Cart.client_id == client_id,
                Cart.user_id == user_id,
                Cart.checked_out.is_(False),
            )
            .options(
                selectinload(Cart.items).selectinload(CartItem.product)
            )
            .order_by(Cart.created_at.desc())
            .execution_options(populate_existing=True)
        )

        return result.scalars().first()

    # -----------------------------
    # CREATE CART (ATOMIC + IDEMPOTENT)
    # -----------------------------
    async def create_cart(
        self,
        merchant_id: str,
        client_id: str,
        user_id: str,
    ) -> Cart:
        """
        Create a new cart for a user, or return existing active cart.
        Flushes within the caller transaction — does not commit.
        """
        existing = await self.get_active_cart(
            merchant_id=merchant_id,
            client_id=client_id,
            user_id=user_id,
        )

        if existing:
            logger.info(f"Returning existing active cart {existing.id} for user {user_id}")
            return existing

        cart = Cart(
            id=generate_uuid(),
            merchant_id=merchant_id,
            client_id=client_id,
            user_id=user_id,
            created_at=datetime.utcnow(),
            checked_out=False,
        )

        self.db.add(cart)
        await self.db.flush()
        new_cart_id = cart.id
        logger.info(f"Created new cart {new_cart_id} for user {user_id}")

        return await self._get_cart_readonly(
            merchant_id=merchant_id,
            client_id=client_id,
            cart_id=new_cart_id
        )

    # -----------------------------
    # ADD ITEM (ATOMIC)
    # -----------------------------
    async def add_item(
        self,
        merchant_id: str,
        client_id: str,
        cart_id: str,
        item: CartItemSchema,
    ) -> Cart:
        """
        Add an item to cart. If item exists, quantity is incremented.
        Uses transaction to ensure atomicity.
        Returns fresh cart state with products loaded.
        """
        async with flush_only(self.db):
            cart = await self._get_cart_for_update(
                merchant_id=merchant_id,
                client_id=client_id,
                cart_id=cart_id,
            )

            if cart.checked_out:
                raise ValueError(f"Cart {cart_id} is already checked out.")

            result = await self.db.execute(
                select(Product).where(
                    Product.id == item.product_id,
                    Product.merchant_id == merchant_id,
                    Product.client_id == client_id,
                )
            )
            product = result.scalar_one_or_none()

            if not product:
                logger.error(f"Product {item.product_id} not found for tenant {merchant_id}:{client_id}")
                raise ValueError(f"Product not found in this store")

            qty = max(int(item.quantity or 1), 1)

            # Reject products that have no price configured. Allowing ₦0 items
            # into the cart produces ₦0 orders, breaks payment logic, and lets
            # customers check out free-of-charge by accident.
            effective_price = float(product.price or 0.0)
            if effective_price <= 0:
                raise ValueError(
                    f"Product '{product.name}' has no price configured and cannot be added to a cart."
                )

            existing_item = next(
                (i for i in cart.items if i.product_id == product.id),
                None,
            )

            if existing_item:
                existing_item.quantity += qty
                logger.info(f"Updated item {product.id} quantity to {existing_item.quantity} in cart {cart_id}")
            else:
                cart_item = CartItem(
                    id=generate_uuid(),
                    cart_id=cart.id,
                    product_id=product.id,
                    quantity=qty,
                    price_at_add=effective_price,
                )
                self.db.add(cart_item)
                logger.info(f"Added new item {product.id} to cart {cart_id}")

        return await self._get_cart_readonly(
            merchant_id=merchant_id,
            client_id=client_id,
            cart_id=cart_id
        )

    # -----------------------------
    # SET ITEM QUANTITY (ATOMIC)
    # -----------------------------
    async def set_item_quantity(
        self,
        merchant_id: str,
        client_id: str,
        cart_id: str,
        product_id: str,
        quantity: int,
    ) -> Cart:
        """
        Set a cart item to an exact quantity.
        quantity=0 removes the item entirely.
        Returns fresh cart state with products loaded.
        """
        if quantity < 0:
            raise ValueError("Quantity cannot be negative")

        async with flush_only(self.db):
            cart = await self._get_cart_for_update(
                merchant_id=merchant_id,
                client_id=client_id,
                cart_id=cart_id,
            )

            if cart.checked_out:
                raise ValueError(f"Cart {cart_id} is already checked out.")

            item = next(
                (i for i in cart.items if str(i.product_id) == str(product_id)),
                None,
            )

            if not item:
                raise ValueError(f"Item not found in cart")

            if quantity == 0:
                await self.db.delete(item)
                logger.info(f"Removed item {product_id} from cart {cart_id} via set_quantity=0")
            else:
                item.quantity = quantity
                logger.info(f"Set item {product_id} quantity to {quantity} in cart {cart_id}")

        return await self._get_cart_readonly(
            merchant_id=merchant_id,
            client_id=client_id,
            cart_id=cart_id
        )

    # -----------------------------
    # REMOVE ITEM (ATOMIC)
    # -----------------------------
    async def remove_item(
        self,
        merchant_id: str,
        client_id: str,
        cart_id: str,
        product_id: str,
    ) -> Cart:
        """
        Remove an item completely from cart.
        Uses transaction to ensure atomicity.
        Returns fresh cart state with remaining items and their products loaded.
        """
        async with flush_only(self.db):
            cart = await self._get_cart_for_update(
                merchant_id=merchant_id,
                client_id=client_id,
                cart_id=cart_id,
            )

            if cart.checked_out:
                raise ValueError(f"Cart {cart_id} is already checked out.")

            item = next(
                (i for i in cart.items if str(i.product_id) == str(product_id)),
                None,
            )

            if not item:
                raise ValueError(f"Item {product_id} not found in cart {cart_id}.")

            await self.db.delete(item)
            logger.info(f"Removed item {product_id} from cart {cart_id}")

        return await self._get_cart_readonly(
            merchant_id=merchant_id,
            client_id=client_id,
            cart_id=cart_id
        )

    # -----------------------------
    # GET CART (READ ONLY) WITH PRODUCTS
    # -----------------------------
    async def get_cart(
        self,
        merchant_id: str,
        client_id: str,
        cart_id: str,
    ) -> Cart | None:
        return await self._get_cart_readonly(
            merchant_id=merchant_id,
            client_id=client_id,
            cart_id=cart_id,
        )

    # -----------------------------
    # CLEAR CART
    # -----------------------------
    async def clear_cart(
        self,
        merchant_id: str,
        client_id: str,
        cart_id: str,
    ) -> None:
        """Remove all items from cart without deleting the cart itself."""
        async with flush_only(self.db):
            cart = await self._get_cart_for_update(
                merchant_id=merchant_id,
                client_id=client_id,
                cart_id=cart_id,
            )

            if cart.checked_out:
                raise ValueError(f"Cart {cart_id} is already checked out.")

            for item in list(cart.items):
                await self.db.delete(item)

    # -----------------------------
    # MARK AS CHECKED OUT
    # -----------------------------
    async def mark_as_checked_out(
        self,
        merchant_id: str,
        client_id: str,
        cart_id: str,
    ) -> None:
        async with flush_only(self.db):
            cart = await self._get_cart_for_update(
                merchant_id=merchant_id,
                client_id=client_id,
                cart_id=cart_id,
            )
            cart.checked_out = True

    # -----------------------------
    # BUILD SUMMARY (IN-MEMORY)
    # -----------------------------
    def _build_summary(self, cart) -> dict:
        """
        Build cart summary from an already-loaded Cart object.
        Avoids a re-query — use this after mutations within the same transaction.
        """
        if not cart or not cart.items:
            return {
                "has_items": False,
                "item_count": 0,
                "total": 0.0,
                "items": [],
            }

        items = []
        total = 0.0

        for item in cart.items:
            subtotal = item.price_at_add * item.quantity
            total += subtotal

            product_name = "Unknown"
            if hasattr(item, "product") and item.product:
                product_name = item.product.name

            items.append({
                "product_id": str(item.product_id),
                "product_name": product_name,
                "quantity": item.quantity,
                "price": float(item.price_at_add),
                "subtotal": float(subtotal),
            })

        return {
            "has_items": True,
            "item_count": sum(i.quantity for i in cart.items),
            "total": total,
            "items": items,
        }

    # -----------------------------
    # GET CART SUMMARY (FROM DB)
    # -----------------------------
    async def get_cart_summary(
        self,
        merchant_id: str,
        client_id: str,
        user_id: str,
    ) -> dict:
        """Get current cart summary via a fresh DB read."""
        cart = await self.get_active_cart(
            merchant_id=merchant_id,
            client_id=client_id,
            user_id=user_id,
        )
        return self._build_summary(cart)
