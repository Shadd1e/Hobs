import os
import hmac
import hashlib
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.session import AsyncSessionLocal
from app.services.payment_service import PaymentService
from app.services.inventory_service import InventoryService
from app.models.order import Order, OrderStatus
from app.models.cart import Cart
from app.models.payment import PaymentStatus
from app.models.client_whatsapp_credential import ClientWhatsAppCredential
from app.models.client_model import Client
from app.services.whatsapp_sender import send_whatsapp_message
from app.conversation.humanizer import Humanizer
from app.services.operator_notification_service import OperatorNotificationService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["Paystack"])


def _verify_paystack_signature(raw_body: bytes, signature: str) -> bool:
    secret = os.getenv("PAYSTACK_WEBHOOK_SECRET", "")
    if not secret:
        logger.error("PAYSTACK_WEBHOOK_SECRET not set")
        return False
    expected = hmac.new(
        secret.encode("utf-8"), raw_body, hashlib.sha512
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/paystack")
async def paystack_webhook(request: Request):

    raw_body = await request.body()
    signature = request.headers.get("x-paystack-signature", "")

    logger.info(
        "Paystack webhook hit — signature_present=%s", bool(signature)
    )

    if not _verify_paystack_signature(raw_body, signature):
        logger.error("Paystack webhook signature mismatch")
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event = payload.get("event")
    data = payload.get("data", {})

    if event != "charge.success":
        logger.info("Paystack webhook: ignoring event '%s'", event)
        return {"status": "ignored"}

    tx_ref = data.get("reference")
    if not tx_ref:
        return {"status": "invalid"}

    # Paystack sends amount in kobo — convert to naira
    webhook_amount = float(data.get("amount", 0)) / 100

    logger.info(
        "Paystack charge.success — tx_ref=%s amount_naira=%.2f",
        tx_ref, webhook_amount,
    )

    # Redis dedup — avoid reprocessing the same transaction
    from app.core.redis_client import redis_service
    dedup_key = f"paystack_processed:{tx_ref}"

    try:
        rc = await redis_service.get_client()
        if await rc.get(dedup_key):
            logger.info("Duplicate Paystack webhook ignored: %s", tx_ref)
            return {"status": "duplicate"}
    except Exception as e:
        logger.warning("Redis dedup check failed, proceeding: %s", e)

    phone_number_id       = None
    order_code            = None
    user_phone            = None
    operator_notify_phone = None
    client_name           = None
    client_id             = None
    order_total           = 0.0
    items_summary         = ""
    order_delivery_type   = "pickup"
    order_delivery_address   = None
    order_delivery_contact   = None
    low_stock_warnings    = []

    async with AsyncSessionLocal() as db:
        async with db.begin():

            # ==================================================
            # CONFIRM PAYMENT
            # ==================================================

            payment_service = PaymentService(db)

            payment = await payment_service.handle_paystack_webhook(
                tx_ref=tx_ref,
                payload=data,
            )

            if not payment or payment.status != PaymentStatus.SUCCEEDED:
                logger.error("Paystack webhook: payment not succeeded for tx_ref=%s", tx_ref)
                try:
                    from app.infrastructure.alerting.slack import alert
                    from app.api.v1.workers.background_tasks import fire_and_forget
                    fire_and_forget(alert(
                        title="Paystack Payment Failed",
                        detail="A card payment webhook was received but the payment did not succeed.",
                        level="critical",
                        fields={"tx_ref": tx_ref},
                    ), name="alert_paystack_payment_failed")
                except Exception:
                    pass
                return {"status": "failed"}

            # ==================================================
            # LOCK ORDER
            # ==================================================

            result = await db.execute(
                select(Order)
                .where(Order.id == payment.order_id)
                .with_for_update()
            )

            order = result.scalar_one_or_none()

            if not order:
                logger.error("Paystack webhook: order not found for payment %s", payment.id)
                try:
                    from app.infrastructure.alerting.slack import alert
                    from app.api.v1.workers.background_tasks import fire_and_forget
                    fire_and_forget(alert(
                        title="Paystack: Order Not Found",
                        detail="Payment succeeded but no matching order was found in the database.",
                        level="critical",
                        fields={"tx_ref": tx_ref, "payment_id": str(payment.id)},
                    ), name="alert_paystack_order_missing")
                except Exception:
                    pass
                return {"status": "order_missing"}

            if order.status == OrderStatus.PAID:
                logger.info("Paystack webhook: order %s already paid", order.id)
                return {"status": "already_paid"}

            # ==================================================
            # AMOUNT VERIFICATION — reject if webhook amount
            # doesn't match what we charged (prevents partial-
            # payment attacks and webhook replay abuse).
            # ==================================================
            expected_amount = float(order.total_amount)
            if abs(webhook_amount - expected_amount) > 0.01:
                logger.error(
                    "Paystack amount mismatch — expected=%.2f webhook=%.2f "
                    "tx_ref=%s order=%s",
                    expected_amount, webhook_amount, tx_ref, order.id,
                )
                try:
                    from app.infrastructure.alerting.slack import alert
                    from app.api.v1.workers.background_tasks import fire_and_forget
                    fire_and_forget(alert(
                        title="Paystack Amount Mismatch ⚠️",
                        detail="Webhook amount does not match order total.",
                        level="critical",
                        fields={
                            "tx_ref":   tx_ref,
                            "expected": f"₦{expected_amount:,.2f}",
                            "received": f"₦{webhook_amount:,.2f}",
                            "order_id": str(order.id),
                        },
                    ), name="slack_paystack_amount_mismatch")
                except Exception:
                    pass
                raise HTTPException(status_code=422, detail="Amount mismatch")

            # ==================================================
            # LOCK CART
            # ==================================================

            result = await db.execute(
                select(Cart)
                .where(Cart.id == order.cart_id)
                .options(selectinload(Cart.items))
                .with_for_update()
            )

            cart = result.scalar_one_or_none()

            if not cart:
                logger.error("Paystack webhook: cart not found for order %s", order.id)
                try:
                    from app.infrastructure.alerting.slack import alert
                    from app.api.v1.workers.background_tasks import fire_and_forget
                    fire_and_forget(alert(
                        title="Paystack: Cart Not Found",
                        detail="Order found but no matching cart — inventory may not have been updated.",
                        level="critical",
                        fields={"tx_ref": tx_ref, "order_id": str(order.id)},
                    ), name="slack_paystack_cart_missing")
                except Exception:
                    pass
                return {"status": "cart_missing"}

            # ==================================================
            # FINALIZE INVENTORY
            # ==================================================

            inventory_service = InventoryService(db)

            inventory_results = []
            for item in cart.items:
                inv = await inventory_service.finalize_sale(
                    merchant_id=order.merchant_id,
                    client_id=order.client_id,
                    product_id=item.product_id,
                    quantity=item.quantity,
                )
                inventory_results.append((item, inv))

            # ==================================================
            # CLOSE CART
            # ==================================================

            if not cart.checked_out:
                cart.checked_out = True
                cart.checked_out_at = datetime.now(timezone.utc)

            # ==================================================
            # UPDATE ORDER
            # ==================================================

            order.status = OrderStatus.PAID
            order.confirmed_at = datetime.now(timezone.utc)
            order_code             = order.order_code
            user_phone             = order.user_id
            order_total            = float(order.total_amount)
            client_id              = order.client_id
            order_delivery_type    = (order.delivery_type.value if order.delivery_type else "pickup")
            order_delivery_address = order.delivery_address
            order_delivery_contact = order.delivery_contact_number

            # Build items summary for operator message
            items_summary = "\n".join(
                f"  • {item.quantity}x {getattr(item.product, 'name', str(item.product_id))}"
                for item in cart.items
            )

            # ==================================================
            # GET PHONE NUMBER ID + OPERATOR PHONE FOR NOTIFICATIONS
            # ==================================================

            client_result = await db.execute(
                select(Client).where(Client.id == order.client_id)
            )
            client_obj = client_result.scalar_one_or_none()
            if client_obj:
                operator_notify_phone = client_obj.operator_notify_phone
                client_name = client_obj.name

            cred_result = await db.execute(
                select(ClientWhatsAppCredential).where(
                    ClientWhatsAppCredential.client_id == order.client_id,
                    ClientWhatsAppCredential.active.is_(True),
                )
            )
            cred = cred_result.scalar_one_or_none()
            if cred:
                phone_number_id = cred.phone_number_id

            # Collect low stock warnings to fire after transaction commits
            for item, inv in inventory_results:
                if getattr(inv, '_low_stock_triggered', False) and operator_notify_phone and phone_number_id:
                    low_stock_warnings.append({
                        "product_name": getattr(item.product, 'name', str(item.product_id)),
                        "remaining": inv._low_stock_remaining,
                        "threshold": inv.low_stock_threshold,
                        "operator_phone": operator_notify_phone,
                        "phone_number_id": phone_number_id,
                        "store_name": client_name or client_id or "",
                    })

            await db.flush()

    # Mark as processed in Redis (24hr TTL) — outside transaction
    try:
        rc = await redis_service.get_client()
        await rc.setex(dedup_key, 86400, "1")
    except Exception as e:
        logger.warning("Redis dedup mark failed: %s", e)

    logger.info(
        "[PAYMENT_SUCCESS] merchant_id=%s order_code=%s tx_ref=%s "
        "amount=%.2f client_id=%s",
        order.merchant_id, order_code, tx_ref,
        order_total, client_id,
    )

    # ==================================================
    # NOTIFY CUSTOMER ON WHATSAPP
    # ==================================================

    if user_phone and phone_number_id and order_code:
        try:
            await send_whatsapp_message(
                to_number=user_phone,
                message=Humanizer.payment_confirmed(order_code, store_name=client_name or None),
                phone_number_id=phone_number_id,
            )
        except Exception as notify_err:
            logger.error(
                "Failed to send payment confirmation to %s: %s",
                user_phone, notify_err,
            )

    # ==================================================
    # NOTIFY OPERATOR ON WHATSAPP
    # ==================================================

    if operator_notify_phone and phone_number_id and order_code:
        try:
            op_notifier = OperatorNotificationService(
                operator_phone=operator_notify_phone,
                phone_number_id=phone_number_id,
                store_name=client_name or client_id,
            )
            await op_notifier.card_payment_confirmed(
                order_code=order_code,
                customer_phone=user_phone or "",
                total=order_total,
                items_summary=items_summary,
                delivery_type=order_delivery_type,
                delivery_address=order_delivery_address,
                delivery_contact=order_delivery_contact,
            )
        except Exception as op_err:
            logger.error("Operator notification failed: %s", op_err)

    # Low stock warnings
    for warning in low_stock_warnings:
        _event = "[OUT_OF_STOCK]" if warning["remaining"] == 0 else "[LOW_STOCK]"
        logger.info(
            "%s merchant_id=%s order_code=%s product=%r remaining=%s threshold=%s client_id=%s",
            _event,
            order.merchant_id, order_code,
            warning["product_name"], warning["remaining"], warning["threshold"],
            client_id,
        )
        try:
            op_notifier = OperatorNotificationService(
                operator_phone=warning["operator_phone"],
                phone_number_id=warning["phone_number_id"],
                store_name=warning["store_name"],
            )
            if warning["remaining"] == 0:
                await op_notifier.out_of_stock(product_name=warning["product_name"])
            else:
                await op_notifier.low_stock_warning(
                    product_name=warning["product_name"],
                    remaining=warning["remaining"],
                    threshold=warning["threshold"],
                )
        except Exception as ls_err:
            logger.error("Low stock notification failed: %s", ls_err)

    return {"status": "ok"}
