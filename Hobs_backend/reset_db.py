#!/usr/bin/env python3
"""
reset_db.py — Wipe the entire database so fresh migrations can run.

RUN THIS ONCE before deploying with the new clean migration.
All data will be permanently deleted.

Usage (from Railway shell or locally with DATABASE_URL set):
    python reset_db.py

What it does:
    1. Drops all tables in the public schema
    2. Drops all custom enum types (orderstatus, paymentstatus, etc.)
    3. Drops the alembic_version table
    After this, deploy normally — entrypoint.sh runs `alembic upgrade head`
    which rebuilds everything from the single clean migration.
"""

import os
import sys
import asyncio
import asyncpg


async def reset(database_url: str):
    # asyncpg needs postgresql:// not postgresql+asyncpg://
    url = database_url
    for prefix in ("postgresql+asyncpg://", "postgres+asyncpg://"):
        if url.startswith(prefix):
            url = url.replace(prefix, "postgresql://", 1)
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)

    print(f"Connecting to database...")
    conn = await asyncpg.connect(url)

    try:
        # ── Drop all tables in dependency order ──────────────────────────────
        print("Dropping all tables...")
        await conn.execute("""
            DO $$ DECLARE
                r RECORD;
            BEGIN
                FOR r IN (
                    SELECT tablename FROM pg_tables
                    WHERE schemaname = 'public'
                ) LOOP
                    EXECUTE 'DROP TABLE IF EXISTS ' || quote_ident(r.tablename) || ' CASCADE';
                END LOOP;
            END $$;
        """)
        print("  ✅ All tables dropped")

        # ── Drop custom enum types ────────────────────────────────────────────
        print("Dropping custom enum types...")
        for enum_name in ['orderstatus', 'paymentstatus', 'whatsapp_message_direction']:
            await conn.execute(f"DROP TYPE IF EXISTS {enum_name} CASCADE")
        print("  ✅ Enum types dropped")

        # ── Drop alembic version tracking ─────────────────────────────────────
        await conn.execute("DROP TABLE IF EXISTS alembic_version CASCADE")
        print("  ✅ alembic_version dropped")

        print()
        print("✅ Database wiped. Deploy now — entrypoint.sh will run migrations automatically.")

    finally:
        await conn.close()


if __name__ == "__main__":
    url = os.getenv("DATABASE_URL")
    if not url:
        print("❌ DATABASE_URL environment variable is not set")
        sys.exit(1)

    confirm = input(
        "\n⚠️  This will DELETE ALL DATA in the database permanently.\n"
        "Type 'wipe' to confirm: "
    ).strip()

    if confirm != "wipe":
        print("Aborted.")
        sys.exit(0)

    asyncio.run(reset(url))
