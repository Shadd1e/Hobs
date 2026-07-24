import logging
from typing import Optional, Dict, Any
from decimal import Decimal
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.domains.payment.models import Payment, PaymentStatus
from app.domains.order.models import Order
from app.schemas.payment import PaymentCreate
from app.shared.models import generate_uuid

logger = logging.getLogger(__name__)


class PaymentService:

    def __init__(self, db: AsyncSession):
        if not db:
            raise ValueError("AsyncSession required")
        self.db = db

    # --------------------------------------------------
    # INTERNAL: LOCK ORDER (TENANT SAFE)
    # --------------------------------------------------
    async def _lock_order(self, order_id: str, merchant_id: str, client_id: str) -> Order:
        result = await self.db.execute(
            select(Order)
            .where(
                Order.id == order_id,
                Order.merchant_id == merchant_id,
                Order.client_id == client_id,
            )
            .with_for_update()
        )
        order = result.scalar_one_or_none()
        if not order:
            raise ValueError("Order not found or tenant mismatch")
        return order

    # --------------------------------------------------
    # INTERNAL: CHECK FOR EXISTING SUCCESSFUL PAYMENT
    # --------------------------------------------------
    async def _order_has_successful_payment(self, order_id: str) -> bool:
        result = await self.db.execute(
            select(Payment)
            .where(
                Payment.order_id == order_id,
                Payment.status == PaymentStatus.SUCCEEDED,
            )
            .limit(1)
        )
        return result.scalars().first() is not None

    # --------------------------------------------------
    # CREATE GENERIC PAYMENT
    # --------------------------------------------------
    async def create(self, payment_in: PaymentCreate) -> Payment:
        order = await self._lock_order(
            payment_in.order_id,
            payment_in.merchant_id,
            payment_in.client_id,
        )

        if await self._order_has_successful_payment(order.id):
            raise ValueError("Order already has successful payment")

        if abs(
            Decimal(str(payment_in.amount)) - Decimal(str(order.total_amount))
        ) > Decimal("0.01"):
            raise ValueError("Payment amount mismatch")

        status = (
            payment_in.status
            if isinstance(payment_in.status, PaymentStatus)
            else PaymentStatus(payment_in.status)
        )

        payment = Payment(
            id=generate_uuid(),
            order_id=order.id,
            merchant_id=order.merchant_id,
            client_id=order.client_id,
            amount=payment_in.amount,
            method=payment_in.method,
            status=status,
            payment_metadata=payment_in.metadata.copy() if payment_in.metadata else None,
        )

        self.db.add(payment)
        await self.db.flush()

        logger.info(
            "Payment created",
            extra={
                "payment_id": payment.id,
                "order_id": payment.order_id,
                "method": payment.method,
                "status": payment.status.value,
            },
        )

        return payment

    # --------------------------------------------------
    # CREATE CASH PAYMENT (PENDING — awaiting store confirmation)
    # --------------------------------------------------
    async def create_cash_payment(
        self,
        *,
        order_id: str,
        merchant_id: str,
        client_id: str,
        amount: Decimal,
        customer_name: Optional[str] = None,
    ) -> Payment:

        metadata = {
            "provider": "cash",
            "customer_name": customer_name,
            "initiated_at": datetime.now(timezone.utc).isoformat(),
        }

        payment_in = PaymentCreate(
            order_id=order_id,
            merchant_id=merchant_id,
            client_id=client_id,
            amount=float(amount),
            method="cash",
            status=PaymentStatus.PENDING,
            metadata=metadata,
        )

        return await self.create(payment_in)

    # --------------------------------------------------
    # UPDATE STATUS
    # --------------------------------------------------
    async def update_status(
        self,
        *,
        payment_id: str,
        merchant_id: str,
        client_id: str,
        new_status: PaymentStatus,
        provider_reference: Optional[str] = None,
        metadata_update: Optional[Dict[str, Any]] = None,
    ) -> Optional[Payment]:

        result = await self.db.execute(
            select(Payment)
            .where(
                Payment.id == payment_id,
                Payment.merchant_id == merchant_id,
                Payment.client_id == client_id,
            )
            .with_for_update()
        )
        payment = result.scalar_one_or_none()

        if not payment:
            return None

        # Idempotent: already succeeded
        if payment.status == PaymentStatus.SUCCEEDED and new_status == PaymentStatus.SUCCEEDED:
            return payment

        if new_status == PaymentStatus.SUCCEEDED:
            if await self._order_has_successful_payment(payment.order_id):
                raise ValueError("Order already has successful payment")

        old_status = payment.status
        payment.status = new_status

        if not payment.payment_metadata:
            payment.payment_metadata = {}

        if provider_reference:
            payment.external_reference = provider_reference
            payment.payment_metadata["provider_reference"] = provider_reference

        if metadata_update:
            payment.payment_metadata.update(metadata_update)

        payment.payment_metadata["updated_at"] = datetime.now(timezone.utc).isoformat()

        await self.db.flush()

        logger.info(
            "Payment status updated",
            extra={
                "payment_id": payment.id,
                "order_id": payment.order_id,
                "old_status": old_status.value,
                "new_status": new_status.value,
            },
        )

        return payment

    # --------------------------------------------------
    # CREATE PAYSTACK PAYMENT (PENDING)
    # --------------------------------------------------
    async def create_paystack_payment(
        self,
        *,
        order_id: str,
        merchant_id: str,
        client_id: str,
        amount: Decimal,
        reference: str,
        customer_phone: Optional[str] = None,
    ) -> Payment:
        metadata = {
            "provider": "paystack",
            "reference": reference,
            "customer_phone": customer_phone,
            "initiated_at": datetime.now(timezone.utc).isoformat(),
        }
        payment_in = PaymentCreate(
            order_id=order_id,
            merchant_id=merchant_id,
            client_id=client_id,
            amount=float(amount),
            method="paystack",
            status=PaymentStatus.PENDING,
            metadata=metadata,
        )
        payment = await self.create(payment_in)
        payment.external_reference = reference
        await self.db.flush()
        return payment

    # --------------------------------------------------
    # HANDLE PAYSTACK WEBHOOK
    # Looks up by external_reference (reference), marks SUCCEEDED
    # --------------------------------------------------
    async def handle_paystack_webhook(
        self,
        *,
        tx_ref: str,
        payload: Dict[str, Any],
    ) -> Payment:
        """Look up payment by external_reference, verify, mark SUCCEEDED."""
        result = await self.db.execute(
            select(Payment)
            .where(Payment.external_reference == tx_ref)
            .with_for_update()
        )
        payment = result.scalar_one_or_none()
        if not payment:
            raise ValueError(f"Payment not found for reference: {tx_ref}")
        if payment.status == PaymentStatus.SUCCEEDED:
            return payment  # idempotent
        return await self.update_status(
            payment_id=payment.id,
            merchant_id=payment.merchant_id,
            client_id=payment.client_id,
            new_status=PaymentStatus.SUCCEEDED,
            provider_reference=tx_ref,
            metadata_update={
                "webhook_received_at": datetime.now(timezone.utc).isoformat(),
                "paystack_payload": payload,
                "provider": "paystack",
            },
        )

    # --------------------------------------------------
    # CONFIRM CASH PAYMENT (called by store WhatsApp number)
    # --------------------------------------------------
    async def confirm_cash_payment(
        self,
        *,
        order: Order,
        merchant_id: str,
        client_id: str,
    ) -> Payment:

        result = await self.db.execute(
            select(Payment)
            .where(
                Payment.order_id == order.id,
                Payment.merchant_id == merchant_id,
                Payment.client_id == client_id,
                Payment.method == "cash",
            )
            .with_for_update()
        )
        payment = result.scalar_one_or_none()

        if not payment:
            raise ValueError("Cash payment record not found")

        if payment.status == PaymentStatus.SUCCEEDED:
            return payment  # idempotent

        payment.status = PaymentStatus.SUCCEEDED

        if not payment.payment_metadata:
            payment.payment_metadata = {}
        payment.payment_metadata["confirmed_at"] = datetime.now(timezone.utc).isoformat()

        await self.db.flush()

        return payment
