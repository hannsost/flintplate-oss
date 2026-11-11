"""Run the requested checks with a mandatory isolated database."""

from __future__ import annotations

import os
import subprocess
import sys

from sqlalchemy.engine import make_url

url = make_url(os.environ["DATABASE_URL"])
if url.database not in {"flintplate", "flintplate_test"}:
    raise RuntimeError("Only FlintPlate local databases are permitted")
os.environ["DATABASE_URL"] = url.set(database="flintplate_test").render_as_string(
    hide_password=False
)
os.environ["APP_ENV"] = "test"
os.environ["FLINTPLATE_REPLACEMENT_WORKER"] = "false"
raise SystemExit(
    subprocess.call(
        [
            sys.executable,
            "-m",
            "pytest",
            *(sys.argv[1:] or ["tests/test_flintplate.py", "-q", "--no-cov"]),
        ],
        env=os.environ,
    )
)
