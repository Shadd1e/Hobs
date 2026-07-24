from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession


@asynccontextmanager
async def transactional(db: AsyncSession):
    """
    Standalone transaction boundary.

    USE THIS only when the caller does NOT already have an active transaction
    (e.g. direct API endpoints, background tasks, scripts).

    DO NOT use this inside whatsapp_handler or any orchestrator that
    opens db.begin() — it will try to commit inside an outer transaction,
    causing InvalidOperationError or silent partial commits.

    For code called from within an active transaction, use db.flush() directly.
    """
    try:
        yield
        await db.commit()
    except Exception:
        await db.rollback()
        raise


@asynccontextmanager
async def flush_only(db: AsyncSession):
    """
    Flush-only context — for service methods called inside an existing transaction.

    Writes pending ORM state to the DB session without committing.
    The outer transaction (db.begin() in the orchestrator) owns the commit.
    On exception, re-raises so the outer transaction can rollback.
    """
    try:
        yield
        await db.flush()
    except Exception:
        raise
