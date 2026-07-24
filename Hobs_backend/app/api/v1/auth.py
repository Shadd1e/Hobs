from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, EmailStr
from app.services.merchant_service import MerchantService
from app.core.security import create_access_token
from app.core.helpers import get_client_ip
from app.db.session import get_db
from sqlalchemy.ext.asyncio import AsyncSession
import logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

@router.post("/login")
async def login(data: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """
    Authenticate merchant and return access token.
    """
    from app.core.redis_client import check_admin_rate_limit
    client_ip = get_client_ip(request)
    rate_key = f"login:{client_ip}:{data.email}"
    if not await check_admin_rate_limit(rate_key):
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts. Try again in 5 minutes.",
            headers={"Retry-After": "300"},
        )

    service = MerchantService(db)
    merchant = await service.authenticate(data.email, data.password)

    if not merchant:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_access_token(subject=merchant.id)
    return {
        "access_token": token,
        "token_type": "bearer",
        "merchant_id": merchant.id,
        "name": merchant.name,
        "email": merchant.email,
        "email_verified": getattr(merchant, "email_verified", False),
    }