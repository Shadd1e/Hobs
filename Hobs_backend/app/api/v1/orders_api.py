import logging
logger = logging.getLogger(__name__)

from fastapi import APIRouter, HTTPException, Depends, status, Query, Request
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.order import OrderRead, OrderStatus
from app.services.order_service import OrderService
from app.db.session import get_db
from app.core.redis_client import rate_limiter

router = APIRouter(prefix="/orders", tags=["Orders"])


def _require_merchant(request: Request) -> str:
    """JWT guard — rejects unauthenticated requests with 401."""
    merchant_id = getattr(request.state, "merchant_id", None)
    if not merchant_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    return merchant_id


# =====================================================
# 📊 REVENUE SUMMARY (STORE OR MERCHANT DASHBOARD)
# — must be registered BEFORE /{order_id} to avoid routing clash
# =====================================================
@router.get("/revenue-summary",
    dependencies=[Depends(rate_limiter("orders-revenue-summary", max_requests=60, window_seconds=60))])
async def revenue_summary(
    request: Request,
    merchant_id: str = Query(...),
    client_id: Optional[str] = Query(None),
    period: str = Query("weekly", regex="^(daily|weekly|monthly)$"),
    count: int = Query(0, ge=0, le=52),   # 0 = use sensible default per period
    db: AsyncSession = Depends(get_db),
):
    """
    Returns revenue totals and a per-period breakdown.
    period: daily (last 30 days) | weekly (last 8 weeks) | monthly (last 12 months)
    count: override number of periods (0 = default)
    Accepts both merchant and client JWTs.
    """
    authed_id = _require_merchant(request)
    if merchant_id != authed_id:
        raise HTTPException(status_code=403, detail="Access denied")

    from sqlalchemy import select, func, text as sa_text
    from app.models.order import Order, OrderStatus as OStatus
    from datetime import datetime, timezone, timedelta

    # Resolve default counts
    default_counts = {"daily": 30, "weekly": 8, "monthly": 12}
    n = count if count > 0 else default_counts[period]

    # Compute the start of the window
    if period == "daily":
        since = datetime.now(timezone.utc) - timedelta(days=n)
    elif period == "weekly":
        since = datetime.now(timezone.utc) - timedelta(weeks=n)
    else:  # monthly
        since = datetime.now(timezone.utc) - timedelta(days=n * 31)

    base_filters = [
        Order.merchant_id == merchant_id,
        Order.created_at >= since,
    ]
    if client_id:
        base_filters.append(Order.client_id == client_id)

    # Total revenue (fulfilled orders only, whole window)
    total_res = await db.execute(
        select(func.coalesce(func.sum(Order.total_amount), 0)).where(
            *base_filters,
            Order.status == OStatus.FULFILLED,
        )
    )
    total_revenue = float(total_res.scalar() or 0)

    # Count by status (all orders in window)
    counts_res = await db.execute(
        select(Order.status, func.count(Order.id)).where(*base_filters).group_by(Order.status)
    )
    counts_by_status = {row[0].value: row[1] for row in counts_res.all()}

    # Period-grouped revenue for the chart (PostgreSQL date_trunc)
    trunc_map = {"daily": "day", "weekly": "week", "monthly": "month"}
    trunc     = trunc_map[period]

    chart_res = await db.execute(
        select(
            func.date_trunc(trunc, Order.created_at).label("period_start"),
            func.coalesce(func.sum(Order.total_amount), 0).label("revenue"),
        ).where(
            *base_filters,
            Order.status == OStatus.FULFILLED,
        ).group_by("period_start").order_by("period_start")
    )

    def _fmt_label(dt, p: str) -> str:
        """Human-readable period label."""
        if p == "daily":
            return dt.strftime("%-d %b")          # e.g. "3 Apr"
        elif p == "weekly":
            return "Wk of " + dt.strftime("%-d %b")  # e.g. "Wk of 24 Mar"
        else:
            return dt.strftime("%b %Y")            # e.g. "Mar 2026"

    daily = [
        {
            "date":    row.period_start.isoformat() if row.period_start else "",
            "label":   _fmt_label(row.period_start, period) if row.period_start else "",
            "revenue": float(row.revenue),
        }
        for row in chart_res.all()
    ]

    return {
        "total_revenue":    total_revenue,
        "counts_by_status": counts_by_status,
        "daily":            daily,
        "period":           period,
        "count":            n,
    }


# =====================================================
# 🚫 ORDER CREATION IS DISABLED (CHECKOUT OWNS CREATION)
# =====================================================
@router.post("/", status_code=status.HTTP_403_FORBIDDEN)
async def create_order_route():
    raise HTTPException(
        status_code=403,
        detail="Direct order creation is disabled. Use /checkout instead."
    )


# =====================================================
# 📋 LIST ORDERS (TENANT-SCOPED) — registered BEFORE /{order_id}
# =====================================================
@router.get("/", response_model=List[OrderRead],
    dependencies=[Depends(rate_limiter("orders-list", max_requests=60, window_seconds=60))])
async def list_orders_route(
    request: Request,
    merchant_id: str = Query(...),
    client_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    # FIX: raised cap from 100 to 200; added offset for pagination.
    # Frontend must check has_more and use offset to fetch the next page.
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db)
):
    authed_id = _require_merchant(request)
    if merchant_id != authed_id:
        raise HTTPException(status_code=403, detail="Access denied")
    service = OrderService(db)
    return await service.list(
        merchant_id=merchant_id,
        client_id=client_id,
        status=status,
        limit=limit,
        offset=offset,
    )


# =====================================================
# 📦 GET ORDER DETAIL WITH ITEMS (DASHBOARD)
# — registered BEFORE /{order_id} to prevent shadowing
# =====================================================
@router.get("/{order_id}/detail")
async def get_order_detail(
    order_id: str,
    request: Request,
    merchant_id: str = Query(...),
    db: AsyncSession = Depends(get_db)
):
    """
    Returns full order detail including cart items, delivery fields,
    and timestamps. Used by the dashboard order detail modal.
    """
    authed_id = _require_merchant(request)
    if merchant_id != authed_id:
        raise HTTPException(status_code=403, detail="Access denied")
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from app.models.order import Order
    from app.models.cart import Cart, CartItem

    result = await db.execute(
        select(Order).where(
            Order.id == order_id,
            Order.merchant_id == merchant_id,
        ).options(selectinload(Order.cart))
    )
    order = result.scalar_one_or_none()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # Fetch store name and address for receipt header
    store_name: str | None = None
    store_address: str | None = None
    if order.client_id:
        from app.models.client_model import Client
        client_result = await db.execute(
            select(Client).where(Client.id == order.client_id)
        )
        client_obj = client_result.scalar_one_or_none()
        if client_obj:
            store_name    = client_obj.name or None
            store_address = client_obj.address or None

    items = []
    if order.cart_id:
        cart_result = await db.execute(
            select(Cart)
            .where(Cart.id == order.cart_id)
            .options(selectinload(Cart.items).selectinload(CartItem.product))
        )
        cart = cart_result.scalar_one_or_none()
        if cart and cart.items:
            for item in cart.items:
                items.append({
                    "product_id":   str(item.product_id),
                    "product_name": getattr(item.product, "name", "Unknown"),
                    "quantity":     item.quantity,
                    "price":        float(item.price_at_add),
                    "subtotal":     float(item.price_at_add) * item.quantity,
                })

    return {
        "id":                       str(order.id),
        "order_code":               order.order_code,
        "merchant_id":              order.merchant_id,
        "client_id":                order.client_id,
        "store_name":               store_name,
        "store_address":            store_address,
        "user_id":                  order.user_id,
        "customer_name":            order.customer_name,
        "payment_method":           order.payment_method,
        "total_amount":             float(order.total_amount),
        "delivery_fee":             float(order.delivery_fee) if order.delivery_fee else None,
        "effective_total":          order.effective_total,
        "status":                   order.status.value,
        # Delivery fields
        "delivery_type":            order.delivery_type.value if order.delivery_type else None,
        "delivery_address":         order.delivery_address,
        "delivery_contact_number":  order.delivery_contact_number,
        # Timestamps
        "created_at":               order.created_at.isoformat() if order.created_at else None,
        "confirmed_at":             order.confirmed_at.isoformat() if order.confirmed_at else None,
        "dispatched_at":            order.dispatched_at.isoformat() if order.dispatched_at else None,
        "fulfilled_at":             order.fulfilled_at.isoformat() if order.fulfilled_at else None,
        "cancelled_at":             order.cancelled_at.isoformat() if order.cancelled_at else None,
        "items":                    items,
    }


# =====================================================
# 🔍 GET ORDER BY ID (TENANT-SCOPED)
# =====================================================
@router.get("/{order_id}", response_model=OrderRead)
async def get_order_route(
    order_id: str,
    request: Request,
    merchant_id: str = Query(...),
    client_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    authed_id = _require_merchant(request)
    if merchant_id != authed_id:
        raise HTTPException(status_code=403, detail="Access denied")
    service = OrderService(db)

    order = await service.get(
        order_id=order_id,
        merchant_id=merchant_id,
        client_id=client_id,
    )

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    return order


# =====================================================
# 🔄 UPDATE ORDER STATUS (TENANT-SCOPED)
# =====================================================
@router.patch("/{order_id}/status", response_model=OrderRead)
async def update_order_status_route(
    order_id: str,
    new_status: OrderStatus,
    request: Request,
    merchant_id: str = Query(...),
    client_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    authed_id = _require_merchant(request)
    if merchant_id != authed_id:
        raise HTTPException(status_code=403, detail="Access denied")

    if new_status == OrderStatus.FULFILLED:
        raise HTTPException(
            status_code=400,
            detail="Order fulfillment must be done via /confirm-cash.",
        )
    if new_status == OrderStatus.OUT_FOR_DELIVERY:
        raise HTTPException(
            status_code=400,
            detail="Use /mark-out-for-delivery to dispatch a delivery order.",
        )

    service = OrderService(db)

    order = await service.update_status(
        order_id=order_id,
        new_status=new_status,
        merchant_id=merchant_id,
        client_id=client_id,
    )

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    return order

# =====================================================
# 🚴 MARK ORDER OUT FOR DELIVERY (DASHBOARD)
# =====================================================
@router.post("/{order_id}/mark-out-for-delivery")
async def mark_out_for_delivery(
    order_id: str,
    request: Request,
    merchant_id: str = Query(...),
    db: AsyncSession = Depends(get_db)
):
    """
    Merchant marks a delivery order as dispatched (OUT_FOR_DELIVERY).
    Sends a WhatsApp notification to the customer.
    """
    authed_id = _require_merchant(request)
    if merchant_id != authed_id:
        raise HTTPException(status_code=403, detail="Access denied")
    from app.services.order_fulfillment_service import OrderFulfillmentService
    from app.services.whatsapp_sender import send_whatsapp_message
    from app.conversation.humanizer import Humanizer

    async with db.begin_nested():
        svc = OrderFulfillmentService(db)
        try:
            dispatch_data = await svc.mark_out_for_delivery(
                order_id=order_id,
                merchant_id=merchant_id,
            )
        except ValueError as e:
            logger.warning("mark_out_for_delivery ValueError: %s", e)
            raise HTTPException(status_code=400, detail="Unable to process request. Please try again.")
        except RuntimeError as e:
            logger.error("mark_out_for_delivery RuntimeError: %s", e)
            raise HTTPException(status_code=500, detail="Unable to process request. Please try again.")

    if dispatch_data is None:
        return {"detail": "Order already out for delivery", "order_id": order_id}

    # Notify customer via WhatsApp (fire-and-forget — failure must not 4xx the merchant)
    try:
        phone_number_id = dispatch_data.get("phone_number_id")
        user_phone      = dispatch_data.get("user_phone")
        contact_number  = dispatch_data.get("delivery_contact_number")

        if phone_number_id and user_phone:
            msg = Humanizer.order_out_for_delivery(
                order_code=dispatch_data["order_code"],
                contact_number=contact_number,
            )
            await send_whatsapp_message(
                to_number=user_phone,
                message=msg,
                phone_number_id=phone_number_id,
            )
    except Exception as notify_err:
        logger.error("Failed to send OUT_FOR_DELIVERY notification: %s", notify_err)

    return {
        "detail":     "Order marked as out for delivery",
        "order_code": dispatch_data["order_code"],
        "status":     "OUT_FOR_DELIVERY",
    }


# =====================================================
# ✅ CONFIRM CASH ORDER (DASHBOARD)
# =====================================================
@router.post("/{order_id}/confirm-cash")
async def confirm_cash_order_dashboard(
    order_id: str,
    request: Request,
    merchant_id: str = Query(...),
    db: AsyncSession = Depends(get_db)
):
    """
    Confirm a cash order from the dashboard.
    Accepts AWAITING_PICKUP (pickup) and OUT_FOR_DELIVERY (delivery).
    Marks FULFILLED and fires receipt to customer.
    """
    authed_id = _require_merchant(request)
    if merchant_id != authed_id:
        raise HTTPException(status_code=403, detail="Access denied")
    from sqlalchemy import select
    from app.models.order import Order, OrderStatus

    result = await db.execute(
        select(Order).where(
            Order.id == order_id,
            Order.merchant_id == merchant_id,
        )
    )
    order = result.scalar_one_or_none()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.payment_method != "cash":
        raise HTTPException(status_code=400, detail="Only cash orders can be confirmed here")

    if order.status == OrderStatus.FULFILLED:
        return {"detail": "Order already fulfilled", "order_code": order.order_code}

    ready_statuses = (OrderStatus.AWAITING_PICKUP, OrderStatus.OUT_FOR_DELIVERY)
    if order.status not in ready_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Order cannot be confirmed — current status: {order.status.value}",
        )

    from datetime import datetime, timezone
    order.status      = OrderStatus.FULFILLED
    order.confirmed_at = datetime.now(timezone.utc)
    await db.commit()

    # Send receipt to customer
    try:
        from sqlalchemy.orm import selectinload
        from app.models.cart import Cart, CartItem
        from app.models.client_model import Client
        from app.services.whatsapp_sender import send_whatsapp_message
        from app.conversation.humanizer import Humanizer
        from app.models.client_whatsapp_credential import ClientWhatsAppCredential

        cred_result = await db.execute(
            select(ClientWhatsAppCredential).where(
                ClientWhatsAppCredential.client_id == order.client_id,
                ClientWhatsAppCredential.active.is_(True),
            )
        )
        cred = cred_result.scalar_one_or_none()

        # Fetch client name for branded receipt header
        client_name: str | None = None
        client_result = await db.execute(
            select(Client).where(Client.id == order.client_id)
        )
        client_obj = client_result.scalar_one_or_none()
        if client_obj:
            client_name = client_obj.name or None

        if cred and order.user_id:
            cart_result = await db.execute(
                select(Cart).where(Cart.id == order.cart_id)
                .options(selectinload(Cart.items).selectinload(CartItem.product))
            )
            cart  = cart_result.scalar_one_or_none()
            items = cart.items if cart else []

            nl = "\n"
            items_lines = nl.join(
                f"{i.quantity}x {getattr(i.product, 'name', '?')} — ₦{float(i.price_at_add) * i.quantity:,.2f}"
                for i in items
            ) or "(items unavailable)"

            receipt_msg = Humanizer.cash_payment_receipt(
                order_code=order.order_code,
                total=float(order.total_amount),
                items_lines=items_lines,
                store_name=client_name,
            )
            await send_whatsapp_message(
                to_number=order.user_id,
                message=receipt_msg,
                phone_number_id=cred.phone_number_id,
            )
    except Exception as e:
        logger.error("Failed to send receipt after dashboard confirmation: %s", e)

    return {
        "detail":     "Order confirmed and receipt sent to customer",
        "order_code": order.order_code,
        "status":     "FULFILLED",
    }
