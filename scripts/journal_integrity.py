"""Independent verification for exported FlintPlate journal chains and saved checkpoints."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from typing import Any

# The exported JSON carries heterogeneous event payloads; validate its envelope explicitly.
def verify(rows: list[dict[str, Any]], *, previous_hash: str = "0" * 64, next_sequence: int = 1,
           checkpoint: dict[str, Any] | None = None) -> dict[str, Any]:
    previous = previous_hash
    sequence = next_sequence
    venue: str | None = None
    checkpoint_seen = checkpoint is None or checkpoint.get("last_sequence") == next_sequence - 1 and checkpoint.get("last_hash") == previous_hash
    for row in rows:
        if row.get("audit_sequence") != sequence or row.get("previous_hash") != previous:
            raise ValueError(f"Broken sequence/anchor at audit event {sequence}")
        if venue is None:
            venue = str(row["venue_id"])
        if str(row["venue_id"]) != venue:
            raise ValueError("A journal chain must contain exactly one venue")
        canonical = row["canonical_payload"]
        digest = hashlib.sha256((previous + "|" + canonical).encode()).hexdigest()
        if digest != row.get("event_hash"):
            raise ValueError(f"Changed canonical payload at event {sequence}")
        payload = json.loads(canonical)
        for field in ("id", "venue_id", "sequence", "audit_sequence", "kind", "aggregate_id", "actor_id", "device_id", "payload"):
            if payload[field] != row[field]:
                raise ValueError(f"Changed exported field {field} at event {sequence}")
        created = datetime.fromisoformat(row["created_at"])
        if created.tzinfo is None or abs(Decimal(str(created.timestamp())) - Decimal(str(payload["created_at_epoch"]))) > Decimal("0.000001"):
            raise ValueError(f"Changed timestamp at event {sequence}")
        if checkpoint and sequence == checkpoint["last_sequence"]:
            if checkpoint["last_hash"] != digest or checkpoint.get("venue_id", venue) != venue:
                raise ValueError("Saved independent checkpoint no longer matches the journal")
            checkpoint_seen = True
        previous = digest
        sequence += 1
    if not checkpoint_seen:
        raise ValueError("Journal is shorter than its independent saved checkpoint")
    return {"venue_id": venue, "verified_events": len(rows), "last_sequence": sequence - 1,
            "last_hash": previous, "next_sequence": sequence, "anchor": previous,
            "assurance": "checkpoint_verified" if checkpoint else "continuity_only"}
