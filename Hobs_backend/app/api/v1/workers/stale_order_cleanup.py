# app/api/v1/workers/stale_order_cleanup.py
"""
Background task: cancels PENDING_PAYMENT card orders that were never paid.

Policy:
- Runs every INTERVAL_MINUTES (default 30).
- Cancels orders stuck in PENDING_PAYMENT for longer than STALE_AFTER_MINUTES (default 120).
- FIX: NOW restores inventory. finalize_sale() is called at checkout for ALL payment methods
  (including card), so inventory IS already deducted when this cleanup runs. Each item's
  stock is restored via adjust_stock() inside the same transaction as the cancellation.
- Re-opens the cart so customer can place a new order.
- Marks the pending payment record as FAILED.
- Sends a WhatsApp notification to the customer so they are not left in silence.
- Fully idempotent: safe to run multiple times.
- Uses skip_locked so multiple workers don't double-process.
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.session import AsyncSessionLocal
from app.models.order import Order, OrderStatus
from app.models.cart import Cart, CartItem
from app.models.product import Product
from app.models.payment import Payment, PaymentStatus
from app.models.client_whatsapp_credential import ClientWhatsAppCredential
from app.services.inventory_service import InventoryService

logger = logging.getLogger(__name__)

STALE_AFTER_MINUTES = 120
INTERVAL_MINUTES    = 30


async def cancel_stale_pending_orders() -> int:
    rc = None
    try:
        from app.core.redis_client import redis_service
        rc = await redis_service.get_client()
        locked = await rc.set("stale_cleanup_lock", "1", nx=True, ex=300)
        if not locked:
            logger.debug("Stale order cleanup skipped — another instance holds the lock")
            return 0
    except Exception as e:
        logger.warning("Could not acquire cleanup lock, proceeding anyway: %s", e)

    try:
        return await _run_cleanup()
    finally:
        if rc is not None:
            try:
                await rc.delete("stale_cleanup_lock")
            except Exception:
                pass


async def _run_cleanup() -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=STALE_AFTER_MINUTES)
    cancelled_count = 0
    cancelled_codes = []

    notifications_to_send = []

    async with AsyncSessionLocal() as db:
        async with db.begin():
            result = await db.execute(
                select(Order)
                .where(
                    Order.status == OrderStatus.PENDING_PAYMENT,
                    Order.payment_method == "card",
                    Order.created_at <= cutoff,
                )
                .with_for_update(skip_locked=True)
            )
            stale_orders = result.scalars().all()

            if not stale_orders:
                return 0

            inventory_service = InventoryService(db)

            for order in stale_orders:
                try:
                    # --------------------------------------------------
                    # PAYMENT: Mark as FAILED
                    # --------------------------------------------------
                    pay_result = await db.execute(
                        select(Payment)
                        .where(
                            Payment.order_id == order.id,
                            Payment.status == PaymentStatus.PENDING,
                        )
                        .with_for_update(skip_locked=True)
                    )
                    payment = pay_result.scalar_one_or_none()
                    if payment:
                        payment.status = PaymentStatus.FAILED
                        logger.info("Payment marked FAILED for stale order %s", order.order_code)

                    # --------------------------------------------------
                    # CART: Load items and reopen
                    # FIX: load cart with items so we can restore inventory below
                    # --------------------------------------------------
                    cart_result = await db.execute(
                        select(Cart)
                        .where(Cart.id == order.cart_id)
                        .options(
                            selectinload(Cart.items).selectinload(CartItem.product)
                        )
                    )
                    cart = cart_result.scalar_one_or_none()
                    if cart and cart.checked_out:
                        cart.checked_out = False
                        cart.checked_out_at = None

                    # --------------------------------------------------
                    # INVENTORY: Restore deducted stock
                    # FIX: finalize_sale() runs at checkout for card orders,
                    # so stock was already taken. Restore it here atomically
                    # inside the same transaction as the cancellation.
                    # --------------------------------------------------
                    if cart and cart.items:
                        for item in cart.items:
                            try:
                                await inventory_service.adjust_stock(
                                    merchant_id=order.merchant_id,
                                    client_id=order.client_id,
                                    product_id=str(item.product_id),
                                    delta=item.quantity,
                                )
                                logger.info(
                                    "Inventory restored: product=%s qty=%d order=%s",
                                    item.product_id, item.quantity, order.order_code,
                                )
                            except Exception as inv_err:
                                logger.error(
                                    "Inventory restore failed for product %s (order %s): %s",
                                    item.product_id, order.order_code, inv_err,
                                )
                                # Non-fatal — continue cancelling other items and the order

                    # --------------------------------------------------
                    # ORDER: Cancel
                    # --------------------------------------------------
                    order.status = OrderStatus.CANCELLED
                    order.cancelled_at = datetime.now(timezone.utc)

                    # --------------------------------------------------
                    # Collect WhatsApp credential for post-commit notify
                    # --------------------------------------------------
                    try:
                        cred_result = await db.execute(
                            select(ClientWhatsAppCredential).where(
                                ClientWhatsAppCredential.client_id == order.client_id,
                                ClientWhatsAppCredential.active.is_(True),
                            )
                        )
                        cred = cred_result.scalar_one_or_none()
                        if cred and order.user_id:
                            notifications_to_send.append({
                                "user_id":         order.user_id,
                                "phone_number_id": cred.phone_number_id,
                                "order_code":      order.order_code,
                            })
                    except Exception as cred_err:
                        logger.warning(
                            "Could not look up credential for stale order %s: %s",
                            order.order_code, cred_err,
                        )

                    cancelled_count += 1
                    cancelled_codes.append(order.order_code)
                    logger.info("Stale order cancelled: %s", order.order_code)

                except Exception as e:
                    logger.error(
                        "Failed to cancel stale order %s: %s",
                        order.order_code, e, exc_info=True,
                    )

    # Transaction committed — now send notifications (fire-and-forget)
    if notifications_to_send:
        from app.services.whatsapp_sender import send_whatsapp_message
        for n in notifications_to_send:
            try:
                await send_whatsapp_message(
                    to_number=n["user_id"],
                    message=(
                        f"Hi! Your order *{n['order_code']}* was not completed — "
                        f"we didn't receive your card payment within 2 hours so it has been cancelled.\n\n"
                        f"No charge was made. Send *new* whenever you're ready to try again! \U0001f6d2"
                    ),
                    phone_number_id=n["phone_number_id"],
                )
                logger.info(
                    "Expiry notification sent to %s for order %s",
                    n["user_id"], n["order_code"],
                )
            except Exception as send_err:
                logger.error(
                    "Failed to send expiry notification for order %s: %s",
                    n["order_code"], send_err,
                )

    if cancelled_count > 0:
        logger.info(
            "Stale order cleanup: cancelled %d orders: %s",
            cancelled_count, ", ".join(cancelled_codes),
        )

    return cancelled_count


async def run_cleanup_loop():
    logger.info(
        "Stale order cleanup loop started — interval=%dm, stale_after=%dm",
        INTERVAL_MINUTES, STALE_AFTER_MINUTES,
    )
    while True:
        await asyncio.sleep(INTERVAL_MINUTES * 60)
        try:
            count = await cancel_stale_pending_orders()
            if count:
                logger.info("Stale cleanup: cancelled %d orders", count)
        except Exception as e:
            logger.error("Stale cleanup loop error: %s", e, exc_info=True)
