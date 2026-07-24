import logging
logger = logging.getLogger(__name__)

# app/db/deps.py — single authoritative get_db dependency
# Provides a session that commits on success, rolls back on exception.
# All REST API endpoints use this via Depends(get_db).
# The whatsapp_handler uses AsyncSessionLocal directly with db.begin()
# for explicit transaction control — it does NOT use this dependency.

from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import AsyncSessionLocal


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()






