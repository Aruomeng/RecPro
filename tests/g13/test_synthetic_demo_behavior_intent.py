from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts.plan_synthetic_demo_behavior_import import build_import_intent


class SyntheticDemoBehaviorIntentTests(unittest.TestCase):
    def _benchmark(self, root: Path) -> Path:
        root.mkdir()
        (root / "manifest.json").write_text(json.dumps({
            "classification": "SYNTHETIC_DEVELOPMENT_ONLY", "confirmation_eligible": False,
            "frozen": True, "dataset_version": "synthetic-v1",
        }), encoding="utf-8")
        (root / "resources.jsonl").write_text(json.dumps({"resource_id": 1, "external_id": "book:one", "title": "测试书", "authors": ["作者"]}) + "\n", encoding="utf-8")
        events = [
            {"event_id": "one", "user_research_id": "synthetic-u-0001", "resource_id": 1, "event_type": "VIEW_RESOURCE", "occurred_at": "2026-01-01T00:00:00.000Z"},
            {"event_id": "two", "user_research_id": "synthetic-u-0001", "resource_id": 1, "event_type": "FAVORITE_RESOURCE", "occurred_at": "2026-01-01T00:01:00.000Z"},
        ]
        (root / "synthetic_events.jsonl").write_text("".join(json.dumps(row) + "\n" for row in events), encoding="utf-8")
        return root

    def test_intent_is_deterministic_bounded_and_zero_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            benchmark = self._benchmark(Path(temporary) / "benchmark")
            first = build_import_intent(benchmark, synthetic_user_id="synthetic-u-0001", target_user_id=1001)
            second = build_import_intent(benchmark, synthetic_user_id="synthetic-u-0001", target_user_id=1001)
        self.assertEqual(first, second)
        self.assertEqual({"user_behavior_event": 2, "profile_update_outbox": 0}, first["expected_append_rows"])
        self.assertEqual(0, first["safety"]["database_connections"])
        self.assertTrue(all(row["enqueue_profile_update"] is False for row in first["events"]))
        self.assertTrue(all(row["reason_code"] == "SYNTHETIC_DEVELOPMENT_ONLY" for row in first["events"]))
        self.assertEqual("测试书", first["events"][0]["resource_title"])

    def test_intent_rejects_real_account_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            benchmark = self._benchmark(Path(temporary) / "benchmark")
            with self.assertRaises(ValueError):
                build_import_intent(benchmark, synthetic_user_id="synthetic-u-0001", target_user_id=10001)


if __name__ == "__main__":
    unittest.main()
