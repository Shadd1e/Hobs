# app/orchestrators/context.py

from dataclasses import dataclass
from typing import Any, Optional, Dict, List
from app.core.tenant_context import TenantContext
from app.conversation.memory import ConversationMemory
from app.services.cart_service import CartService
from app.services.checkout_service import CheckoutService
from app.services.fuzzy_match import FuzzyMatcher


@dataclass
class ConversationContext:
    tenant: TenantContext
    db: Any
    user_phone: str
    user_text: str
    phone_number_id: str
    memory: ConversationMemory
    cart_service: CartService
    checkout_service: CheckoutService
    matcher: FuzzyMatcher
    cart_summary: Optional[Dict] = None
    cart_items: Optional[List] = None