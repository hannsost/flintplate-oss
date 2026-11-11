"""Exercise migrations in a newly created, disposable *_test database only.

Usage: python scripts/check_migrations.py 050
The argument is the previous revision to downgrade to before upgrading again.
No existing application or test database is modified.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid

import asyncpg
from sqlalchemy.engine import make_url


async def main() -> None:
    url = make_url(os.environ["DATABASE_URL"])
    name = f"palmscout_migration_{uuid.uuid4().hex}_test"
    connection = await asyncpg.connect(
        host=url.host,
        port=url.port or 5432,
        user=url.username,
        password=url.password,
        database="postgres",
    )
    created = False
    try:
        await connection.execute(f'CREATE DATABASE "{name}"')
        created = True
        env = {
            **os.environ,
            "DATABASE_URL": url.set(database=name).render_as_string(hide_password=False),
        }
        for direction, revision in [
            ("upgrade", "head"),
            ("downgrade", sys.argv[1]),
            ("upgrade", "head"),
        ]:
            subprocess.run(["alembic", direction, revision], env=env, check=True)
        print("Empty database upgrade, downgrade and re-upgrade passed.")
    finally:
        if created:
            await connection.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
        await connection.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python scripts/check_migrations.py PREVIOUS_REVISION")
    asyncio.run(main())
