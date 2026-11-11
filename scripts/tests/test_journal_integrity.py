from __future__ import annotations
import hashlib
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from journal_integrity import verify


def chain():
    rows = []
    previous = "0" * 64
    for sequence in range(1, 4):
        payload = dict(id=str(sequence), venue_id="venue", sequence=sequence, audit_sequence=sequence, kind="test", aggregate_id="a", actor_id=None, device_id=None, payload={}, created_at_epoch=0)
        canonical = json.dumps(payload)
        digest = hashlib.sha256((previous + "|" + canonical).encode()).hexdigest()
        rows.append({**payload, "created_at": "1970-01-01T00:00:00+00:00", "canonical_payload": canonical, "event_hash": digest, "previous_hash": previous})
        previous = digest
    return rows


class IntegrityTests(unittest.TestCase):
    def test_continuity_is_not_claimed_to_prove_completeness(self):
        self.assertEqual(verify(chain()[:2])["assurance"], "continuity_only")

    def test_checkpoint_rejects_valid_but_truncated_prefix(self):
        checkpoint = verify(chain())
        with self.assertRaisesRegex(ValueError, "shorter"):
            verify(chain()[:2], checkpoint=checkpoint)

    def test_checkpoint_accepts_growth(self):
        self.assertEqual(verify(chain(), checkpoint=verify(chain()[:2]))["assurance"], "checkpoint_verified")

    def test_export_field_mutation_rejected(self):
        rows = chain()
        rows[1]["payload"] = {"changed": True}
        with self.assertRaisesRegex(ValueError, "Changed exported field"):
            verify(rows)

    def test_cross_venue_checkpoint_rejected(self):
        checkpoint = {**verify(chain()), "venue_id": "other"}
        with self.assertRaisesRegex(ValueError, "checkpoint"):
            verify(chain(), checkpoint=checkpoint)


if __name__ == "__main__":
    unittest.main()
