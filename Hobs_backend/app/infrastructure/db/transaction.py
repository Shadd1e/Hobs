from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession


@asynccontextmanager
async def transactional(db: AsyncSession):
    """
    Savepoint-based nested transaction.

    If an outer db.begin() is already active (e.g. from whatsapp_handler),
    this uses a SAVEPOINT so the outer transaction stays in charge.
    If called standalone (tests, scripts), it starts its own transaction.
    """
    if db.in_transaction():
        async with db.begin_nested():
            yield db
    else:
        async with db.begin():
            yield db
