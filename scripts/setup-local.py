"""Create/extend isolated credentials, preserving every existing value."""

from __future__ import annotations

import os
import secrets
import tempfile
from pathlib import Path


def ensure_config(target: Path) -> None:
    if target.is_symlink():
        raise ValueError("Local configuration must be a regular file")
    content = target.read_text() if target.exists() else ""
    keys = {
        line.split("=", 1)[0].strip()
        for line in content.splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    }
    additions = []
    for key, size in (
        ("FLINTPLATE_DB_PASSWORD", 24),
        ("FLINTPLATE_RUNTIME_DB_PASSWORD", 24),
        ("FLINTPLATE_REDIS_PASSWORD", 24),
        ("SECRET_KEY", 48),
    ):
        if key not in keys:
            additions.append(f"{key}={secrets.token_hex(size)}")
    if "APP_ENV" not in keys:
        additions.append("APP_ENV=development")
    if not additions:
        target.chmod(0o600)
        return
    content = content.rstrip("\n") + ("\n" if content else "") + "\n".join(additions) + "\n"
    # mkstemp starts with mode 0600, including while replacing an existing file.
    descriptor, temporary = tempfile.mkstemp(prefix=".flintplate-env-", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)


if __name__ == "__main__":
    ensure_config(Path(__file__).resolve().parents[1] / ".env.flintplate")
    print("Lokale FlintPlate-Konfiguration vorhanden. Zugangsdaten werden nicht ausgegeben.")
