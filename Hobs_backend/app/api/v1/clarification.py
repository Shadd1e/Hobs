from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.deps import get_db
from app.services.clarification_service import ClarificationService
import logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/clarifications", tags=["clarifications"])


def get_clarification_service(db: AsyncSession = Depends(get_db)):
    return ClarificationService(db)


@router.get("/")
async def list_clarifications(service: ClarificationService = Depends(get_clarification_service)):
    return await service.get_all()


@router.post("/{client_id}")
async def clarify_message(
    client_id: str,
    message: str,
    merchant_id: str = None,
    service: ClarificationService = Depends(get_clarification_service),
):
    response = await service.clarify(merchant_id or "SYSTEM", client_id, message)
    return {"response": response}