from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
from typing import Optional, List

from app.models.clarification import Clarification
from app.services.deepseek_service import classify_intent
import logging
logger = logging.getLogger(__name__)


class ClarificationService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_clarification(
        self,
        merchant_id: str,
        client_id: str,
        question: str,
        session_id: Optional[str] = None,
    ) -> Clarification:
        clar = Clarification(
            merchant_id=merchant_id,
            client_id=client_id,
            session_id=session_id,
            question=question,
            resolved=False,
            created_at=datetime.utcnow(),
        )
        self.db.add(clar)
        return clar

    async def resolve_clarification(
        self,
        clarification_id: str,
        resolution_text: str,
    ) -> Clarification:
        res = await self.db.execute(
            select(Clarification).where(Clarification.id == clarification_id)
        )
        clar = res.scalars().first()
        if not clar:
            raise ValueError("Clarification not found")
        clar.resolved = True
        clar.resolution = resolution_text
        return clar

    async def clarify(
        self,
        merchant_id: str,
        client_id: str,
        message: str,
    ) -> str:
        result = await classify_intent(message)
        return result.get("reply") or result.get("intent", "")

    async def list_clarifications(
        self,
        merchant_id: str,
        client_id: str,
    ) -> List[Clarification]:
        res = await self.db.execute(
            select(Clarification).where(
                Clarification.merchant_id == merchant_id,
                Clarification.client_id == client_id,
            )
        )
        return res.scalars().all()