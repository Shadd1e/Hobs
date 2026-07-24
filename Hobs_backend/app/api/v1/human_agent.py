import logging
logger = logging.getLogger(__name__)

# app/api/v1/human_agent.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from app.schemas.human_agent import HumanAgentCreate, HumanAgentRead
from app.services.human_agent_service import HumanAgentService
from app.db.deps import get_db

router = APIRouter(prefix="/human-agent", tags=["HumanAgent"])

@router.post("/", response_model=HumanAgentRead)
async def create_human_task(task_in: HumanAgentCreate, db: AsyncSession = Depends(get_db)):
    service = HumanAgentService(db)
    task = await service.create_task(task_in)
    if not task:
        raise HTTPException(status_code=400, detail="Failed to create human agent task.")
    return task


@router.post("/escalate")
async def escalate_message(
    merchant_id: str, client_id: str, message: str, db: AsyncSession = Depends(get_db)
):
    service = HumanAgentService(db)
    return await service.escalate_message(merchant_id, client_id, message)


@router.get("/", response_model=list[HumanAgentRead])
async def list_tasks(status: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    service = HumanAgentService(db)
    return await service.list_tasks(status)


@router.put("/{task_id}/status", response_model=HumanAgentRead)
async def update_task_status(task_id: str, new_status: str, agent_name: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    service = HumanAgentService(db)
    task = await service.update_status(task_id, new_status, agent_name)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task
