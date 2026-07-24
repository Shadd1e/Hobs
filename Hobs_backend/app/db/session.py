# app/db/session.py

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
)
from sqlalchemy.orm import sessionmaker

from app.core.config import settings


# ======================================================
# ENGINE
# ======================================================

engine = create_async_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=15,
    max_overflow=20,
    future=True,
)


# ======================================================
# SESSION FACTORY
# ======================================================

AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


# ======================================================
# FASTAPI DEPENDENCY
# ======================================================

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session