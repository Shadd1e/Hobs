import logging
from typing import Optional, List
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.domains.conversation.models import HumanAgent, WhatsappMessageLog
from app.schemas.human_agent import HumanAgentCreate
from app.shared.models import generate_uuid

logger = logging.getLogger(__name__)


class HumanAgentService:
    """
    Human agent escalation service.
    No commits — caller owns transaction.
    """

    def __init__(self, db: AsyncSession):
        if not db:
            raise ValueError("AsyncSession must be provided")
        self.db = db

    async def create_task(self, task_in: HumanAgentCreate) -> HumanAgent:
        task = HumanAgent(
            id=generate_uuid(),
            cart_id=task_in.cart_id,         # cart_id, not order_id
            client_id=task_in.client_id,
            merchant_id=task_in.merchant_id,
            total_amount=task_in.total_amount,
            status="pending",                  # plain string — HumanAgent.status is String
        )
        self.db.add(task)
        return task

    async def escalate_message(
        self,
        merchant_id: str,
        client_id: str,
        message: str,
    ) -> str:
        result = await self.db.execute(
            select(HumanAgent).where(
                HumanAgent.merchant_id == merchant_id,
                HumanAgent.client_id == client_id,
                HumanAgent.status == "pending",
            )
        )
        task = result.scalars().first()

        if not task:
            return "No human agent task available right now."

        self.db.add(
            WhatsappMessageLog(
                id=generate_uuid(),
                merchant_id=merchant_id,
                client_id=client_id,
                from_number=client_id,
                to_number="AGENT",
                direction="incoming",
                message=message,
            )
        )

        return f"Message escalated to human agent (cart: {task.cart_id})"

    async def list_tasks(self, status: Optional[str] = None) -> List[HumanAgent]:
        stmt = select(HumanAgent)
        if status:
            stmt = stmt.where(HumanAgent.status == status)
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def update_status(
        self,
        task_id: str,
        new_status: str,
        agent_name: Optional[str] = None,
    ) -> Optional[HumanAgent]:
        result = await self.db.execute(
            select(HumanAgent).where(HumanAgent.id == task_id)
        )
        task = result.scalars().first()
        if not task:
            return None
        task.status = new_status
        if agent_name:
            task.assigned_agent = agent_name
        return task
