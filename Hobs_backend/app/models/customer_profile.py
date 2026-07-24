# app/models/customer_profile.py
"""
CustomerProfile — cross-store identity record for WhatsApp customers.

A customer is identified by their phone number. This record is created on
their very first message to ANY store on the platform and is shared across
all stores. It stores their name (collected once, reused everywhere), tracks
activity timestamps, and remembers their last order for repeat-order UX.

Design notes:
  - phone_number is stored WITHOUT the leading '+' to match the format used
    in Order.user_id and WhatsApp webhook payloads (e.g. '2348012345678').
  - The name field is intentionally nullable — the customer may not have
    provided it yet (e.g. if they skipped the onboarding prompt).
  - last_order_summary stores a compact JSON blob written at checkout:
      {"order_code": "X7K4M2PQ", "total": 3000.0,
       "items": [{"name": "Noodles", "qty": 2}, ...], "store": "The Altekflo"}
    It is scoped per (customer × store) via last_order_client_id so a customer
    shopping at two stores sees the right repeat-order offer in each.
  - This table is NOT tenant-scoped for name/timestamps, but last_order fields
    track which client (store) the repeat-order prompt should apply to.
"""

import json
from typing import Optional, List, Dict, Any

from sqlalchemy import Column, String, DateTime, Text, func
from app.db.base import Base
import logging

logger = logging.getLogger(__name__)


class CustomerProfile(Base):
    __tablename__ = "customer_profiles"

    # ── Primary key ────────────────────────────────────────────────────────────
    phone_number = Column(
        String(20),
        primary_key=True,
        comment="WhatsApp number without leading '+'. Matches Order.user_id format.",
    )

    # ── Customer-provided name ─────────────────────────────────────────────────
    name = Column(
        String(100),
        nullable=True,
        comment=(
            "Name as provided by the customer during first-contact onboarding. "
            "Used to personalise all subsequent bot messages across every store."
        ),
    )

    # ── Last order (for repeat-order UX) ──────────────────────────────────────
    last_order_summary = Column(
        Text,
        nullable=True,
        comment=(
            "JSON blob of the customer's most recent completed order at last_order_client_id. "
            "Format: {order_code, total, items: [{name, qty}], store}. "
            "Written at checkout. Used to offer a one-tap repeat-order on next visit."
        ),
    )
    last_order_client_id = Column(
        String(20),
        nullable=True,
        comment="client_id of the store where last_order_summary was placed.",
    )

    # ── Timestamps ─────────────────────────────────────────────────────────────
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="When this profile was first created (very first message ever sent).",
    )

    last_seen_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment=(
            "Updated on every inbound message from this customer. "
            "Useful for analytics and reactivation campaigns."
        ),
    )

    # ── Helper properties ──────────────────────────────────────────────────────
    @property
    def display_name(self) -> str:
        return self.name if self.name else "there"

    @property
    def is_named(self) -> bool:
        return bool(self.name and self.name.strip())

    def get_last_order(self) -> Optional[Dict[str, Any]]:
        """Parse last_order_summary JSON. Returns None if absent or invalid."""
        if not self.last_order_summary:
            return None
        try:
            return json.loads(self.last_order_summary)
        except Exception:
            return None

    def set_last_order(
        self,
        *,
        order_code: str,
        total: float,
        items: List[Dict[str, Any]],
        store: str,
        client_id: str,
    ) -> None:
        """Serialise and store the last order. Call before db.flush()."""
        self.last_order_summary = json.dumps({
            "order_code": order_code,
            "total":      total,
            "items":      items,   # [{"name": ..., "qty": ...}]
            "store":      store,
        })
        self.last_order_client_id = client_id

    def __repr__(self):
        return (
            f"<CustomerProfile("
            f"phone={self.phone_number!r}, "
            f"name={self.name!r}, "
            f"last_seen={self.last_seen_at})>"
        )
