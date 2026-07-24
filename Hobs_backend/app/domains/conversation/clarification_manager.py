import logging
logger = logging.getLogger(__name__)

# clarification_manager.py - orchestrates clarifications with DeepSeek/human agent
from sqlalchemy.ext.asyncio import AsyncSession  # auto-patched
from app.domains.conversation.clarification_service import ClarificationService
from app.infrastructure.ai.deepseek_service import DeepSeekService # may be async; handled below


class ClarificationManager:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.service = ClarificationService(db)

    async def ask_clarification(
        self,
        merchant_id: str,
        client_id: str,
        question: str,
        session_id: str | None = None,
    ):
        """
        Save clarification and attempt automated answer via DeepSeek.
        If DeepSeek returns an answer, resolve the clarification automatically.
        """
        # Create clarification (async)
        c = await self.service.create(merchant_id, client_id, question, session_id)

        # attempt answer via DeepSeek (may be async or sync)
        answer = None
        try:
            # If process_with_deepseek is async, await it. If it's sync, call it directly.
            maybe = DeepSeekService(merchant_id=merchant_id, client_id=client_id, message=question)
            if hasattr(maybe, "__await__"):
                answer = await maybe
            else:
                answer = maybe
        except Exception:
            answer = None

        if answer:
            # resolve asynchronously
            await self.service.resolve(c.id, answer)
            return {"clarification": c, "answer": answer}

        # leave unresolved for human
        return {"clarification": c, "answer": None}
