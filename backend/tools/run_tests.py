"""Run tests with the separate migration role, only against flintplate_test."""

from __future__ import annotations

import os
import sys

from sqlalchemy.engine import make_url


def test_environment(source: dict[str, str]) -> dict[str, str]:
    url = make_url(source["DATABASE_URL"])
    if url.database not in {"flintplate", "flintplate_test"} or url.username != "flintplate":
        raise ValueError("Tests require the isolated FlintPlate migration identity")
    environment = dict(source)
    environment["DATABASE_URL"] = url.set(database="flintplate_test").render_as_string(
        hide_password=False
    )
    environment["APP_ENV"] = "test"
    environment["AI_MOCK_MODE"] = "true"
    environment["FLINTPLATE_REPLACEMENT_WORKER"] = "false"
    environment["SMTP_HOST"] = ""
    # Tests don't need the real runtime password, JWT signer or provider keys.
    environment["SECRET_KEY"] = "isolated-flintplate-test-signing-key"
    environment.pop("FLINTPLATE_RUNTIME_DB_PASSWORD", None)
    return environment


def main() -> None:
    environment = test_environment(dict(os.environ))
    os.execvpe(sys.executable, [sys.executable, "-m", "pytest", *sys.argv[1:]], environment)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError):
        print(
            "Teststart verweigert: separate FlintPlate-Testdatenbank erforderlich.", file=sys.stderr
        )
        raise SystemExit(1) from None
