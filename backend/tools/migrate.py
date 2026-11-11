"""Owner-only migration job. Never used as the API startup command."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import asyncpg
from sqlalchemy.engine import make_url

from tools.runtime_db import main as provision_runtime


def main() -> int:
    url = make_url(os.environ["DATABASE_URL"])
    if url.database != "flintplate" or url.username != "flintplate":
        raise ValueError("Migration job requires the local FlintPlate owner database")
    # A failed migration must not continue to provisioning or claim readiness.
    result = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=False)
    if result.returncode:
        return result.returncode
    asyncio.run(provision_runtime())
    # Only the dedicated upload mount is writable by UID 10001. API source and
    # administrative tools remain read-only and are never chowned to that UID.
    uploads = Path("/data/uploads")
    if uploads.is_dir() and os.geteuid() == 0:
        os.chown(uploads, 10001, 10001)
        for directory, subdirectories, files in os.walk(uploads, followlinks=False):
            for name in subdirectories + files:
                path = Path(directory) / name
                if not path.is_symlink():
                    os.chown(path, 10001, 10001)
    print("Migrationen und Runtime-Rechte eingerichtet; API kann gestartet werden.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (asyncpg.PostgresError, OSError, ValueError, KeyError):
        print("Administrativer Job fehlgeschlagen; keine Zugangsdaten ausgegeben.", file=sys.stderr)
        raise SystemExit(1) from None
