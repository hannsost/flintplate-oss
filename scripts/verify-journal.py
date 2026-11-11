#!/usr/bin/env python3
"""Verify continuity and, when supplied, an independently saved journal checkpoint."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from journal_integrity import verify

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("file", type=Path)
parser.add_argument("--previous-hash", default="0" * 64)
parser.add_argument("--next-sequence", type=int, default=1)
parser.add_argument("--checkpoint", type=Path, help="Saved venue checkpoint; detects tail truncation too")
args = parser.parse_args()
try:
    rows = json.loads(args.file.read_text())
    checkpoint = json.loads(args.checkpoint.read_text()) if args.checkpoint else None
    if checkpoint and "data" in checkpoint:
        venue_id = rows[0]["venue_id"] if rows else None
        checkpoint = next((entry for entry in checkpoint["data"]["venues"] if entry["venue_id"] == venue_id), None)
        if checkpoint is None:
            raise ValueError("No matching venue checkpoint in the saved archive")
    result = verify(rows, previous_hash=args.previous_hash,
                    next_sequence=args.next_sequence, checkpoint=checkpoint)
except (ValueError, KeyError, TypeError) as exc:
    raise SystemExit(str(exc)) from exc
print(json.dumps(result))
