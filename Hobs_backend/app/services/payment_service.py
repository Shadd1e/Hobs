# app/services/payment_service.py

import logging
from typing import Optional, Dict, Any
from decimal import Decimal
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.payment import Payment, PaymentStatus
from app.models.order import Order
from app.schemas.payment import PaymentCreate
from app.models.utils import generate_uuid

logger = logging.getLogger(__name__)


class PaymentService:
    """
    Payment domain service.

    Rules:
    - No commits / rollbacks — caller owns transaction
    - Row locking on state changes
    - Strict tenant isolation
    - Prevent double successful payments
    """

    def __init__(self, db: AsyncSession):
        if not db:
            raise ValueError("AsyncSession required")
        self.db = db

    # =====================================================
    # INTERNAL HELPERS
    # =====================================================

    async def _get_order(self, order_id: str, merchant_id: str, client_id: str) -> Order:
        result = await self.db.execute(
            select(Order).where(
                Order.id == order_id,
                Order.merchant_id == merchant_id,
                Order.client_id == client_id,
            )
            # NO with_for_update() here — caller locks if needed
        )
        order = result.scalar_one_or_none()
        if not order:
            raise ValueError("Order not found or tenant mismatch")
        return order

    async def _order_has_successful_payment(self, order_id: str) -> bool:
        result = await self.db.execute(
            select(Payment).where(
                Payment.order_id == order_id,
                Payment.status == PaymentStatus.SUCCEEDED,
            ).limit(1)
        )
        return result.scalars().first() is not None

    # =====================================================
    # CREATE PAYMENT (CORE)
    # =====================================================

    async def create(self, payment_in: PaymentCreate) -> Payment:

        order = await self._get_order(
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

        metadata = dict(payment_in.metadata) if payment_in.metadata else {}

        payment = Payment(
            id=generate_uuid(),
            order_id=order.id,
            merchant_id=order.merchant_id,
            client_id=order.client_id,
            amount=payment_in.amount,
            method=payment_in.method,
            status=status,
            payment_metadata=metadata,
        )

        self.db.add(payment)
        await self.db.flush()

        logger.info(
            "Payment created — id=%s order=%s method=%s status=%s",
            payment.id, payment.order_id, payment.method, payment.status.value,
        )

        return payment

    # =====================================================
    # PAYSTACK PAYMENT CREATION
    # =====================================================

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
        payment = await self.create(PaymentCreate(
            order_id=order_id,
            merchant_id=merchant_id,
            client_id=client_id,
            amount=float(amount),
            method="paystack",
            status=PaymentStatus.PENDING,
            metadata={
                "provider": "paystack",
                "provider_reference": reference,
                "reference": reference,
                "customer_phone": customer_phone,
                "initiated_at": datetime.now(timezone.utc).isoformat(),
            },
        ))
        payment.external_reference = reference
        await self.db.flush()
        return payment

    # =====================================================
    # CASH PAYMENT CREATION
    # =====================================================

    async def create_cash_payment(
        self,
        *,
        order_id: str,
        merchant_id: str,
        client_id: str,
        amount: Decimal,
        customer_name: Optional[str] = None,
    ) -> Payment:
        """
        Create a pending cash payment record.
        Status transitions to SUCCEEDED when store confirms pickup.
        """
        return await self.create(PaymentCreate(
            order_id=order_id,
            merchant_id=merchant_id,
            client_id=client_id,
            amount=float(amount),
            method="cash",
            status=PaymentStatus.PENDING,
            metadata={
                "provider": "cash",
                "customer_name": customer_name,
                "initiated_at": datetime.now(timezone.utc).isoformat(),
            },
        ))

    # =====================================================
    # UPDATE STATUS
    # =====================================================

    async def update_status(
        self,
        *,
        payment_id: str,
        merchant_id: str,
        client_id: str,
        new_status: PaymentStatus,
        provider_reference: Optional[str] = None,
        metadata_update: Optional[Dict[str, Any]] = None,
        skip_succeeded_check: bool = False,
    ) -> Optional[Payment]:

        result = await self.db.execute(
            select(Payment).where(
                Payment.id == payment_id,
                Payment.merchant_id == merchant_id,
                Payment.client_id == client_id,
            ).with_for_update()
        )

        payment = result.scalar_one_or_none()
        if not payment:
            return None

        if payment.status == PaymentStatus.SUCCEEDED and new_status == PaymentStatus.SUCCEEDED:
            return payment

        if new_status == PaymentStatus.SUCCEEDED and not skip_succeeded_check:
            if await self._order_has_successful_payment(payment.order_id):
                raise ValueError("Order already has successful payment")

        old_status = payment.status
        payment.status = new_status

        if not payment.payment_metadata:
            payment.payment_metadata = {}

        if provider_reference:
            payment.payment_metadata["provider_reference"] = provider_reference
        if metadata_update:
            payment.payment_metadata.update(metadata_update)

        payment.payment_metadata["updated_at"] = datetime.now(timezone.utc).isoformat()

        await self.db.flush()

        logger.info(
            "Payment status updated — id=%s %s → %s",
            payment.id, old_status.value, new_status.value,
        )

        return payment

    # =====================================================
    # PAYSTACK WEBHOOK (IDEMPOTENT)
    # =====================================================

    async def handle_paystack_webhook(
        self,
        *,
        tx_ref: str,
        payload: Dict[str, Any],
    ) -> Payment:
        """Look up payment by external_reference, mark SUCCEEDED."""
        result = await self.db.execute(
            select(Payment).where(
                Payment.external_reference == tx_ref
            ).with_for_update()
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
            skip_succeeded_check=True,
            metadata_update={
                "webhook_received_at": datetime.now(timezone.utc).isoformat(),
                "paystack_payload": payload,
                "provider": "paystack",
            },
        )

    # =====================================================
    # CASH CONFIRMATION
    # =====================================================

    async def confirm_cash_payment(
        self,
        *,
        order: Order,
        merchant_id: str,
        client_id: str,
    ) -> Payment:

        result = await self.db.execute(
            select(Payment).where(
                Payment.order_id == order.id,
                Payment.merchant_id == merchant_id,
                Payment.client_id == client_id,
            ).with_for_update()
        )

        payment = result.scalar_one_or_none()
        if not payment:
            raise ValueError("Payment not found")
        if payment.method != "cash":
            raise ValueError("Not a cash payment")
        if payment.status == PaymentStatus.SUCCEEDED:
            return payment

        payment.status = PaymentStatus.SUCCEEDED
        await self.db.flush()
        return payment
