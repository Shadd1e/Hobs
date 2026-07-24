import logging
logger = logging.getLogger(__name__)

# app/services/human_agent_service.py

from typing import Optional, List
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.human_agent import HumanAgent
from app.models.whatsapp_message_log import WhatsappMessageLog
from app.schemas.human_agent import HumanAgentCreate
from app.models.utils import generate_uuid


class HumanAgentService:
    """
    Human agent escalation service.

    RULES:
    - No commits
    - No flushes
    - Returns ORM objects only
    - Checkout owns the transaction
    """

    def __init__(self, db: AsyncSession):
        if not db:
            raise ValueError("AsyncSession must be provided")
        self.db = db

    # -----------------------------
    # CREATE HUMAN AGENT TASK
    # -----------------------------
    async def create_task(self, task_in: HumanAgentCreate) -> HumanAgent:
        task = HumanAgent(
            id=generate_uuid(),
            order_id=task_in.order_id,
            client_id=task_in.client_id,
            merchant_id=task_in.merchant_id,
            status=PaymentStatus.PENDING,
            created_at=datetime.utcnow(),
        )

        self.db.add(task)
        return task

    # -----------------------------
    # ESCALATE MESSAGE TO AGENT
    # -----------------------------
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
                to_number="AGENT_NUMBER_PLACEHOLDER",
                direction="incoming",
                message=message,
                created_at=datetime.utcnow(),
            )
        )

        return f"Escalated to human agent for order {task.order_id}"

    # -----------------------------
    # LIST TASKS
    # -----------------------------
    async def list_tasks(self, status: Optional[str] = None) -> List[HumanAgent]:
        stmt = select(HumanAgent)
        if status:
            stmt = stmt.where(HumanAgent.status == status)

        result = await self.db.execute(stmt)
        return result.scalars().all()

    # -----------------------------
    # UPDATE TASK STATUS
    # -----------------------------
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
