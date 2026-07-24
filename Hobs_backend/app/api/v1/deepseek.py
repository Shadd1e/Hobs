import logging
logger = logging.getLogger(__name__)

# app/api/v1/routes/deepseek.py

from fastapi import APIRouter, Depends, HTTPException, Request, Header, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.deepseek_service import DeepSeekService

router = APIRouter(prefix="/deepseek", tags=["DeepSeek"])


@router.post("/query")
async def query_deepseek(
    request: Request,
    message: str,
    db: AsyncSession = Depends(get_db),
    x_merchant_id: str | None = Header(default=None, alias="X-Merchant-ID"),
    x_client_id: str | None = Header(default=None, alias="X-Client-ID"),
):
    """
    Interpret a message using DeepSeek, perform inventory search,
    and return fuzzy-matched results for a tenant.
    """
    merchant_id = x_merchant_id or getattr(request.state, "merchant_id", None)
    client_id = x_client_id or getattr(request.state, "client_id", None)

    if not merchant_id or not client_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing merchant or client ID",
        )

    try:
        service = DeepSeekService(db)
        result = await service.interpret_and_search(
            merchant_id=merchant_id,
            client_id=client_id,
            message=message,
        )
        return {
            "merchant_id": merchant_id,
            "client_id": client_id,
            "query": message,
            "result": result,
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"DeepSeek query failed: {str(e)}",
        )
