from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts.plan_current_synthetic_profile_demo import build_current_profile_demo_intent
from tests.g13.test_synthetic_demo_behavior_intent import SyntheticDemoBehaviorIntentTests


class CurrentSyntheticProfileDemoIntentTests(unittest.TestCase):
    def _sixteen_event_benchmark(self, root: Path) -> Path:
        benchmark = SyntheticDemoBehaviorIntentTests()._benchmark(root)
        events = [json.loads(line) for line in (benchmark / "synthetic_events.jsonl").read_text(encoding="utf-8").splitlines()]
        for index in range(2, 16):
            events.append({
                "event_id": f"generated-{index}",
                "user_research_id": "synthetic-u-0001",
                "resource_id": 1,
                "event_type": "VIEW_RESOURCE" if index % 2 == 0 else "FAVORITE_RESOURCE",
                "occurred_at": f"2026-01-01T00:{index:02d}:00.000Z",
            })
        (benchmark / "synthetic_events.jsonl").write_text(
            "".join(json.dumps(item) + "\n" for item in events), encoding="utf-8",
        )
        return benchmark

    def test_intent_is_chronological_bounded_and_has_one_batch_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            benchmark = self._sixteen_event_benchmark(Path(temporary) / "benchmark")
            intent = build_current_profile_demo_intent(
                benchmark, base_occurred_at="2026-09-01T12:00:00.000Z",
            )
        self.assertEqual(1002, intent["target"]["user_id"])
        self.assertEqual(16, len(intent["events"]))
        self.assertEqual("2026-09-01T12:00:00.000Z", intent["events"][0]["occurred_at"])
        self.assertEqual("2026-09-01T12:15:00.000Z", intent["events"][-1]["occurred_at"])
        self.assertEqual(1, intent["expected_append_rows"]["profile_update_outbox"])
        self.assertEqual(intent["events"][-1]["event_uuid"], intent["profile_refresh_batch"]["source_event_uuid"])
        self.assertEqual(0, intent["safety"]["database_writes"])

    def test_rejects_timestamp_without_offset(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            benchmark = self._sixteen_event_benchmark(Path(temporary) / "benchmark")
            with self.assertRaises(ValueError):
                build_current_profile_demo_intent(benchmark, base_occurred_at="2026-09-01T12:00:00")


if __name__ == "__main__":
    unittest.main()
