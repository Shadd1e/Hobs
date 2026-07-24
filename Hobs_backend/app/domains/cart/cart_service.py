import logging
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domains.cart.models import Cart, CartItem
from app.domains.product.models import Product
from app.schemas.cart import CartItemSchema
from app.infrastructure.db.transaction import transactional

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
        Atomic operation within transaction.
        """
        async with transactional(self.db):
            # Check for existing active cart first
            existing = await self.get_active_cart(
                merchant_id=merchant_id,
                client_id=client_id,
                user_id=user_id,
            )

            if existing:
                logger.info(f"Returning existing active cart {existing.id} for user {user_id}")
                return existing

            # Create new cart if none exists
            cart = Cart(
                id=generate_uuid(),
                merchant_id=merchant_id,
                client_id=client_id,
                user_id=user_id,
                created_at=datetime.utcnow(),
                checked_out=False,
            )

            self.db.add(cart)
            # Capture ID inside transaction
            new_cart_id = cart.id
            logger.info(f"Created new cart {new_cart_id} for user {user_id}")

        # Return fresh cart with items loaded using captured ID
        return await self._get_cart_readonly(
            merchant_id=merchant_id,
            client_id=client_id,
            cart_id=new_cart_id
        )

    # -----------------------------
    # ADD ITEM (ATOMIC) - FIXED WITH TENANT-SCOPED PRODUCT LOOKUP
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
        async with transactional(self.db):
            cart = await self._get_cart_for_update(
                merchant_id=merchant_id,
                client_id=client_id,
                cart_id=cart_id,
            )

            if cart.checked_out:
                raise ValueError(f"Cart {cart_id} is already checked out.")

            # FIX: Load product with TENANT SCOPING to prevent cross-tenant contamination
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

            # Ensure quantity is at least 1
            qty = max(int(item.quantity or 1), 1)

            # Check for existing item
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
                    price_at_add=product.price,
                )
                self.db.add(cart_item)
                logger.info(f"Added new item {product.id} to cart {cart_id}")

        # Return fresh cart with all items and products loaded
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
        async with transactional(self.db):
            cart = await self._get_cart_for_update(
                merchant_id=merchant_id,
                client_id=client_id,
                cart_id=cart_id,
            )

            if cart.checked_out:
                raise ValueError(f"Cart {cart_id} is already checked out.")

            # Find the item
            item = next((i for i in cart.items if i.product_id == product_id), None)

            if not item:
                raise ValueError(f"Item {product_id} not found in cart {cart_id}.")

            await self.db.delete(item)
            logger.info(f"Removed item {product_id} from cart {cart_id}")

        # Return fresh cart with remaining items and products loaded
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
        """
        Get cart by ID with tenant safety.
        Eager loads items and their associated products.
        Read-only operation, no lock.
        """
        return await self._get_cart_readonly(
            merchant_id=merchant_id,
            client_id=client_id,
            cart_id=cart_id
        )

    # -----------------------------
    # CLEAR CART (ATOMIC)
    # -----------------------------
    async def clear_cart(
        self,
        merchant_id: str,
        client_id: str,
        cart_id: str,
    ) -> Cart:
        """
        Remove all items from cart.
        Returns the cleared cart (empty items list).
        """
        async with transactional(self.db):
            cart = await self._get_cart_for_update(
                merchant_id=merchant_id,
                client_id=client_id,
                cart_id=cart_id,
            )

            if cart.checked_out:
                raise ValueError(f"Cart {cart_id} is already checked out.")

            # Delete all items
            for item in list(cart.items):
                await self.db.delete(item)
            
            logger.info(f"Cleared all items from cart {cart_id}")

        # Return fresh empty cart
        return await self._get_cart_readonly(
            merchant_id=merchant_id,
            client_id=client_id,
            cart_id=cart_id
        )

    # -----------------------------
    # MARK CART AS CHECKED OUT
    # -----------------------------
    async def mark_as_checked_out(
        self,
        merchant_id: str,
        client_id: str,
        cart_id: str,
    ) -> Cart:
        """
        Mark cart as checked out. Called by checkout service after successful order.
        """
        async with transactional(self.db):
            cart = await self._get_cart_for_update(
                merchant_id=merchant_id,
                client_id=client_id,
                cart_id=cart_id,
            )

            if cart.checked_out:
                logger.warning(f"Cart {cart_id} already marked as checked out")
                return cart

            cart.checked_out = True
            logger.info(f"Marked cart {cart_id} as checked out")

        # Return updated cart
        return await self._get_cart_readonly(
            merchant_id=merchant_id,
            client_id=client_id,
            cart_id=cart_id
        )

    # -----------------------------
    # GET CART SUMMARY WITH PRODUCT NAMES (HELPER)
    # -----------------------------
    async def get_cart_summary(
        self,
        merchant_id: str,
        client_id: str,
        user_id: str,
    ) -> dict:
        """
        Get a summary of the active cart with product names.
        Useful for WhatsApp display and context building.
        """
        cart = await self.get_active_cart(
            merchant_id=merchant_id,
            client_id=client_id,
            user_id=user_id
        )
        
        if not cart or not cart.items:
            return {
                "has_items": False,
                "item_count": 0,
                "total": 0,
                "items": []
            }
        
        items_summary = []
        total = 0  # Compute total once
        
        for item in cart.items:
            # FIX: Better error logging if product is missing
            if not item.product:
                logger.error(f"Cart {cart.id} has item {item.id} with missing product {item.product_id}")
                product_name = f"Product {item.product_id[:8]}"
            else:
                product_name = item.product.name
                
            subtotal = item.price_at_add * item.quantity
            total += subtotal
            
            items_summary.append({
                "product_id": item.product_id,
                "product_name": product_name,
                "name": product_name,
                "quantity": item.quantity,
                "price": item.price_at_add,
                "subtotal": subtotal
            })
        
        return {
            "has_items": True,
            "cart_id": cart.id,
            "item_count": sum(i.quantity for i in cart.items),
            "total": total,
            "items": items_summary
        }