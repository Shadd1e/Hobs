from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request
from .security import decode_access_token
from .tenant_context import TenantContext

class TenantMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Webhooks resolve their own tenant from the WhatsApp phone number ID
        if "/webhook" in request.url.path:
            return await call_next(request)

        merchant_id = None
        client_id   = None
        token_type  = "merchant"

        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            try:
                decoded = decode_access_token(token)
                if isinstance(decoded, dict):
                    # Client-scoped token: { sub: client_id, merchant_id, type }
                    merchant_id = decoded.get("merchant_id")
                    client_id   = decoded.get("sub")
                    token_type  = decoded.get("type", "client")
                elif isinstance(decoded, str):
                    # Merchant token: sub is merchant_id
                    merchant_id = decoded
                    token_type  = "merchant"
            except Exception:
                pass

        if merchant_id:
            request.state.merchant_id = merchant_id
            request.state.client_id   = client_id
            request.state.token_type  = token_type
            request.state.tenant = TenantContext(
                merchant_id=merchant_id,
                client_id=client_id,
            )

        return await call_next(request)
