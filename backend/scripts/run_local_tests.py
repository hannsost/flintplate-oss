"""Run an isolated test suite and persist its outcome independently of the caller.

Useful with docker compose exec -d backend python scripts/run_local_tests.py.
The report directory must be unique per concurrently running test process.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.engine import make_url


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default="hireos_test")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if not args.database.endswith("_test"):
        parser.error("The database name must end with _test.")
    source = make_url(os.environ["DATABASE_URL"])
    if source.database == args.database and os.environ.get("APP_ENV") != "test":
        parser.error("Refusing to use the configured application database outside APP_ENV=test.")
    args.report.mkdir(parents=True, exist_ok=False)
    status = args.report / "status.json"
    started = datetime.now(UTC).isoformat()
    status.write_text(json.dumps({"status": "running", "started_at": started}))
    env = dict(os.environ)
    env["DATABASE_URL"] = source.set(database=args.database).render_as_string(hide_password=False)
    if env.get("REDIS_URL"):
        env["REDIS_URL"] = (
            make_url(env["REDIS_URL"]).set(database="1").render_as_string(hide_password=False)
        )
    env.update(APP_ENV="test", AI_MOCK_MODE="true", SMTP_HOST="", PYTHONUNBUFFERED="1")
    options = args.pytest_args or ["--cov=app", "--cov-fail-under=80", "-q", "--tb=short"]
    if options and options[0] == "--":
        options = options[1:]
    with (args.report / "pytest.log").open("w") as output:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", *options],
            env=env,
            stdout=output,
            stderr=subprocess.STDOUT,
            check=False,
        )
    temporary = status.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            {
                "status": "passed" if result.returncode == 0 else "failed",
                "exit_code": result.returncode,
                "started_at": started,
                "finished_at": datetime.now(UTC).isoformat(),
            }
        )
    )
    temporary.replace(status)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
