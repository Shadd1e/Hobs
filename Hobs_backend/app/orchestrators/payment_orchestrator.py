# app/orchestrators/payment_orchestrator.py

import logging
from app.conversation.humanizer import Humanizer
from app.orchestrators.context import ConversationContext
from app.services.order_fulfillment_service import OrderFulfillmentService

logger = logging.getLogger(__name__)


class PaymentOrchestrator:

    def __init__(self, context: ConversationContext):
        self.ctx = context
        self.db  = context.db
        self.memory = context.memory

        self.merchant_id     = str(context.tenant.merchant_id)
        self.client_id       = str(context.tenant.client_id)
        self.user_id         = context.user_phone
        self.phone_number_id = context.phone_number_id

    # ==========================================================
    # CONFIRM CASH PAYMENT (intent: confirm_cash)
    # Triggered when operator WhatsApp sends: confirm ORDERCODE
    # ==========================================================

    async def confirm_cash(self, order_code: str) -> str:
        """
        Confirms a cash order via WhatsApp.

        Flow:
        1. OrderFulfillmentService validates and marks order FULFILLED
        2. We send a receipt to the CUSTOMER via WhatsApp
        3. We return a success message to the OPERATOR

        The receipt send is fire-and-forget — a WhatsApp failure does not
        roll back the fulfilment, which is already committed by this point.
        """
        if not order_code:
            return "Please send: confirm ORDERCODE"

        fulfillment_service = OrderFulfillmentService(self.db)

        try:
            receipt = await fulfillment_service.confirm_pickup(
                order_code=order_code,
                from_whatsapp_number=self.user_id,
            )

        except ValueError as e:
            err = str(e)
            if "Unauthorized" in err or "unauthorized" in err:
                return "❌ Unauthorized. Only the registered store number may confirm orders."
            return f"❌ {err}"

        except RuntimeError as e:
            logger.error("Cash confirmation DB error for %s: %s", order_code, e)
            return "❌ Could not confirm order. Please try again."

        except Exception as e:
            logger.exception("Cash confirmation failure for %s: %s", order_code, e)
            return "❌ Could not confirm order."

        # Already fulfilled (idempotent path)
        if receipt is None:
            return f"ℹ️ Order {order_code} was already confirmed."

        # -------------------------------------------------------
        # SEND RECEIPT TO CUSTOMER
        # Fire-and-forget — never let a send failure affect the
        # operator's confirmation response or roll back the order.
        # -------------------------------------------------------
        try:
            phone_number_id = receipt.get("phone_number_id") or self.phone_number_id
            customer_phone  = receipt.get("user_phone")

            if phone_number_id and customer_phone:
                from app.services.whatsapp_sender import send_whatsapp_message

                newline     = "\n"
                items_lines = newline.join(
                    f"{i['quantity']}x {i['name']} — ₦{i['price'] * i['quantity']:,.2f}"
                    for i in receipt.get("items", [])
                ) or "(items unavailable)"

                receipt_msg = Humanizer.cash_payment_receipt(
                    order_code=receipt["order_code"],
                    total=receipt["total_amount"],
                    items_lines=items_lines,
                    store_name=self.ctx.tenant.client_name or None,
                )

                await send_whatsapp_message(
                    to_number=customer_phone,
                    message=receipt_msg,
                    phone_number_id=phone_number_id,
                )
                logger.info(
                    "Receipt sent to customer %s for order %s",
                    customer_phone, order_code,
                )
            else:
                logger.warning(
                    "Could not send receipt for order %s — "
                    "missing phone_number_id or customer_phone",
                    order_code,
                )

        except Exception as send_err:
            # Log but never raise — the order is confirmed regardless
            logger.error(
                "Failed to send receipt to customer for order %s: %s",
                order_code, send_err,
            )

        return f"✅ Order {order_code} confirmed! Receipt sent to customer."
