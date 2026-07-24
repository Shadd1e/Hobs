import sys
import os
from pathlib import Path
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# -------------------------------------------------
# Ensure project root is on PYTHONPATH
# -------------------------------------------------
BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(BASE_DIR))

# -------------------------------------------------
# Import Base and load ALL models
# -------------------------------------------------
from app.db.base import Base
import app.models  # this loads all models via app/models/__init__.py

target_metadata = Base.metadata

# -------------------------------------------------
# Alembic config
# -------------------------------------------------
config = context.config

if config.config_file_name:
    fileConfig(config.config_file_name)

# -------------------------------------------------
# Database URL (Railway / local)
# -------------------------------------------------
database_url = os.getenv("ALEMBIC_DB_URL") or os.getenv("DATABASE_URL")

if not database_url:
    raise RuntimeError("DATABASE_URL or ALEMBIC_DB_URL must be set")

# Convert asyncpg → psycopg2 for Alembic
if database_url.startswith("postgresql+asyncpg"):
    database_url = database_url.replace(
        "postgresql+asyncpg",
        "postgresql+psycopg2"
    )

config.set_main_option("sqlalchemy.url", database_url)

# -------------------------------------------------
# Offline migrations
# -------------------------------------------------
def run_migrations_offline():
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()

# -------------------------------------------------
# Online migrations
# -------------------------------------------------
def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()