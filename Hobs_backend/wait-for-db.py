#!/usr/bin/env python3

import os
import sys
import asyncio
import asyncpg


async def check_db(db_url: str, max_attempts: int = 40, delay: float = 2.0) -> bool:
    print("🔍 Waiting for database...")

    for attempt in range(1, max_attempts + 1):
        try:
            print(f"   Attempt {attempt}/{max_attempts}")

            conn = await asyncpg.connect(db_url, timeout=5.0)

            version = await conn.fetchval("SELECT version();")
            await conn.close()

            print("✅ Database ready!")
            print(f"   {version.split(',')[0]}")
            return True

        except asyncpg.InvalidCatalogNameError:
            # Railway sometimes creates DB lazily
            print("⚠️  Database not initialized yet — waiting for Alembic")
            return True

        except Exception as e:
            if attempt < max_attempts:
                print(f"   ⏳ Not ready: {str(e).splitlines()[0]}")
                await asyncio.sleep(delay)
            else:
                print("❌ Database never became ready")
                print(e)
                return False

    return False


if __name__ == "__main__":
    db_url = os.getenv("DATABASE_URL")

    if not db_url:
        print("❌ DATABASE_URL is not set")
        sys.exit(1)

    max_attempts = int(os.getenv("DB_WAIT_ATTEMPTS", "40"))
    delay = float(os.getenv("DB_WAIT_DELAY", "2.0"))

    ok = asyncio.run(check_db(db_url, max_attempts, delay))
    sys.exit(0 if ok else 1)
