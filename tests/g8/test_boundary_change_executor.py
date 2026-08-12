from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import tempfile
import unittest

from scripts.build_g5_feedback_http_plan import canonical, sha256_bytes
from scripts.build_g8_boundary_change_plan import EXPECTED_DELTAS, build_plan
from scripts.execute_g8_boundary_change_plan import (
    INTERACTION_DELTAS,
    assert_delta,
    impression_command,
    load_and_validate_plan,
)


def facts(*, item_id: int, resource_id: int, rank_no: int) -> dict[str, object]:
    return {
        "task": {"id": "11111111-1111-1111-1111-111111111111", "user_id": 1001},
        "record": {"id": 24},
        "item": {"id": item_id, "resource_id": resource_id, "rank_no": rank_no},
        "resource_tags": ({"tag_id": item_id, "weight": 1.0, "confidence": 1.0, "source": "IMPORT"},),
        "resource_states": (),
        "outbox_statuses": {"DONE": 1},
        "uuid_absence": {"impression_uuid": 0, "feedback_uuid": 0, "behavior_uuid": 0},
        "latest_behavior_at": None,
        "user_interest_tag_ids": (),
        "user_negative_preference_keys": (),
    }


def plan() -> dict[str, object]:
    return build_plan(
        run_id="g8-boundary-executor-test-001",
        baseline_path=Path("artifacts/baseline.json").resolve(),
        baseline={"compose_project": "recpro-test"},
        baseline_raw=b"{}",
        current_counts={table: 10 for table in EXPECTED_DELTAS},
        identity={"database": "recpro"},
        read_target=facts(item_id=131, resource_id=6299, rank_no=2),
        exposure_target=facts(item_id=132, resource_id=7999, rank_no=3),
        base_at=datetime(2026, 8, 12, 9, 30, tzinfo=UTC),
        uuids={
            "duration_impression": "22222222-2222-4222-8222-222222222222",
            "ratio_impression": "33333333-3333-4333-8333-333333333333",
            "read_impression": "44444444-4444-4444-8444-444444444444",
            "read_feedback": "55555555-5555-4555-8555-555555555555",
        },
    )


class BoundaryChangeExecutorTest(unittest.TestCase):
    def test_plan_validation_requires_exact_approval_hash(self) -> None:
        payload = plan()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            observed = load_and_validate_plan(
                path,
                approved_plan_id=str(payload["plan_id"]),
                approved_plan_hash=str(payload["plan_hash"]),
            )
        self.assertEqual(payload["plan_hash"], observed["plan_hash"])

    def test_tampered_plan_is_rejected(self) -> None:
        payload = plan()
        payload["scenarios"]["duration_below_threshold"]["visible_ms"] = 998
        payload.pop("plan_hash")
        approved_hash = sha256_bytes(canonical(payload))
        payload["plan_hash"] = approved_hash
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_and_validate_plan(
                    path,
                    approved_plan_id=str(payload["plan_id"]),
                    approved_plan_hash=approved_hash,
                )

    def test_commands_preserve_exact_exposure_boundaries(self) -> None:
        payload = plan()
        scenarios = payload["scenarios"]
        exposure = facts(item_id=132, resource_id=7999, rank_no=3)
        duration = impression_command(scenarios["duration_below_threshold"], exposure)
        ratio = impression_command(scenarios["ratio_below_threshold"], exposure)
        self.assertEqual((999, 0.8), (duration.visible_ms, duration.max_visible_ratio))
        self.assertEqual((1000, 0.49), (ratio.visible_ms, ratio.max_visible_ratio))
        self.assertEqual(3, duration.position)

    def test_exact_interaction_and_final_budgets(self) -> None:
        self.assertEqual(12, sum(INTERACTION_DELTAS.values()))
        self.assertEqual(20, sum(EXPECTED_DELTAS.values()))
        assert_delta({"a": 5}, {"a": 6}, {"a": 1})
        with self.assertRaises(ValueError):
            assert_delta({"a": 5}, {"a": 7}, {"a": 1})


if __name__ == "__main__":
    unittest.main()
