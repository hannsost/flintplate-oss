#!/usr/bin/env python3
"""Save journal checkpoints outside the API container after independent chain verification.

Run on the local host, not inside the application container. Existing checkpoints
must still occur in the database; deleting a suffix or a venue fails the job.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import subprocess
from datetime import UTC, datetime

from journal_integrity import verify

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--directory", type=Path, required=True)
args = parser.parse_args()
directory = args.directory.resolve()
if directory.is_relative_to(root / "backend"):
    raise SystemExit("Checkpoints must be outside the API's mounted backend directory")
os.umask(0o077)
directory.mkdir(parents=True, exist_ok=True, mode=0o700)
key_path = directory / ".signing-key"
if not key_path.exists():
    with key_path.open("xb") as handle:
        handle.write(secrets.token_bytes(32))
key = key_path.read_bytes()
latest = directory / "latest.json"
previous = json.loads(latest.read_text()) if latest.exists() else None
if previous:
    signed = json.dumps(previous["data"], sort_keys=True, separators=(",", ":")).encode()
    if not hmac.compare_digest(previous["signature"], hmac.new(key, signed, hashlib.sha256).hexdigest()):
        raise SystemExit("Independent checkpoint signature is invalid")
command = ["docker", "compose", "-f", "compose.yaml", "--env-file", ".env.flintplate", "exec", "-T", "db", "psql", "-U", "flintplate", "-d", "flintplate", "-qAt", "-c",
           "SELECT coalesce(json_agg(e ORDER BY venue_id,audit_sequence),'[]'::json) FROM fp_events e"]
result = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)
if result.returncode:
    raise SystemExit("Journal database export failed; no checkpoint was changed")
rows = json.loads(result.stdout)
by_venue: dict[str, list[dict]] = {}
for row in rows:
    by_venue.setdefault(row["venue_id"], []).append(row)
old = {row["venue_id"]: row for row in previous["data"]["venues"]} if previous else {}
if set(old) - set(by_venue):
    raise SystemExit("A venue with an independent checkpoint disappeared")
try:
    venues = [verify(events, checkpoint=old.get(venue)) for venue, events in sorted(by_venue.items())]
except (ValueError, KeyError, TypeError) as exc:
    raise SystemExit(f"Journal verification failed: {exc}") from exc
now = datetime.now(UTC)
data = {"created_at": now.isoformat(), "venues": venues,
        "previous_file_hash": hashlib.sha256(latest.read_bytes()).hexdigest() if latest.exists() else None}
canonical = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
envelope = {"data": data, "signature": hmac.new(key, canonical, hashlib.sha256).hexdigest()}
encoded = json.dumps(envelope, indent=2) + "\n"
archive = directory / (now.strftime("%Y%m%dT%H%M%S%fZ") + ".json")
archive.write_text(encoded)
temporary = directory / "latest.pending"
with temporary.open("w") as handle:
    handle.write(encoded)
    handle.flush()
    os.fsync(handle.fileno())
temporary.replace(latest)
print(json.dumps({"verified_venues": len(venues), "verified_events": sum(len(events) for events in by_venue.values()), "checkpoint": str(archive)}))
