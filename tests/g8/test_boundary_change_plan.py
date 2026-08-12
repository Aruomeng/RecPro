from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import unittest

from scripts.build_g8_boundary_change_plan import EXPECTED_DELTAS, build_plan


def target(*, item_id: int, resource_id: int) -> dict[str, object]:
    return {
        "task": {"id": "11111111-1111-1111-1111-111111111111", "user_id": 1001},
        "record": {"id": 24},
        "item": {"id": item_id, "resource_id": resource_id},
        "resource_tags": ({"tag_id": item_id, "weight": 1.0, "confidence": 1.0, "source": "IMPORT"},),
        "resource_states": (),
        "outbox_statuses": {"DONE": 1},
        "uuid_absence": {"impression_uuid": 0, "feedback_uuid": 0, "behavior_uuid": 0},
        "latest_behavior_at": None,
        "user_interest_tag_ids": (),
        "user_negative_preference_keys": (),
    }


class BoundaryChangePlanTest(unittest.TestCase):
    def build(self):
        counts = {table: 10 for table in EXPECTED_DELTAS}
        return build_plan(
            run_id="g8-boundary-change-plan-test-001",
            baseline_path=Path("artifacts/baseline.json").resolve(),
            baseline={"compose_project": "recpro-test"},
            baseline_raw=b"{}",
            current_counts=counts,
            identity={"database": "recpro"},
            read_target=target(item_id=131, resource_id=6299),
            exposure_target=target(item_id=132, resource_id=7999),
            base_at=datetime(2026, 8, 12, 9, 30, tzinfo=UTC),
            uuids={
                "duration_impression": "22222222-2222-4222-8222-222222222222",
                "ratio_impression": "33333333-3333-4333-8333-333333333333",
                "read_impression": "44444444-4444-4444-8444-444444444444",
                "read_feedback": "55555555-5555-4555-8555-555555555555",
            },
        )

    def test_plan_freezes_three_cases_and_zero_authorization(self) -> None:
        plan = self.build()
        self.assertEqual(["A07", "A09", "A10"], plan["case_ids"])
        self.assertEqual(20, plan["max_changes"])
        self.assertFalse(plan["safety_assertions"]["business_writes_authorized"])
        operations = {target["table"]: target["operation"] for target in plan["targets"]}
        self.assertEqual("APPEND_AND_STATUS_UPDATE", operations["profile_update_outbox"])
        self.assertEqual("CONTROLLED_PROJECTION_UPDATE", operations["user_profile"])
        self.assertEqual("READY_FOR_EXPLICIT_APPROVAL", plan["executor_status"])

    def test_thresholds_and_already_read_semantics_are_exact(self) -> None:
        scenarios = self.build()["scenarios"]
        self.assertEqual(999, scenarios["duration_below_threshold"]["visible_ms"])
        self.assertEqual(0.49, scenarios["ratio_below_threshold"]["max_visible_ratio"])
        self.assertEqual("ALREADY_READ", scenarios["already_read"]["reason_code"])
        self.assertEqual("READ", scenarios["already_read"]["expected_resource_state"])

    def test_target_budget_is_exact_and_non_decreasing(self) -> None:
        plan = self.build()
        observed = {item["table"]: item["expected_delta"] for item in plan["targets"]}
        self.assertEqual(EXPECTED_DELTAS, observed)
        self.assertTrue(all(item["expected_after_count"] >= item["expected_before_count"] for item in plan["targets"]))

    def test_naive_mysql_latest_behavior_is_interpreted_as_utc(self) -> None:
        read_target = target(item_id=131, resource_id=6299)
        exposure_target = target(item_id=132, resource_id=7999)
        read_target["latest_behavior_at"] = "2030-01-20T12:06:00"
        exposure_target["latest_behavior_at"] = "2030-01-20T12:06:00"
        common = {
            "run_id": "g8-boundary-latest-time-test-001",
            "baseline_path": Path("artifacts/baseline.json").resolve(),
            "baseline": {"compose_project": "recpro-test"},
            "baseline_raw": b"{}",
            "current_counts": {table: 10 for table in EXPECTED_DELTAS},
            "identity": {"database": "recpro"},
            "read_target": read_target,
            "exposure_target": exposure_target,
            "uuids": {
                "duration_impression": "22222222-2222-4222-8222-222222222222",
                "ratio_impression": "33333333-3333-4333-8333-333333333333",
                "read_impression": "44444444-4444-4444-8444-444444444444",
                "read_feedback": "55555555-5555-4555-8555-555555555555",
            },
        }
        with self.assertRaises(ValueError):
            build_plan(base_at=datetime(2030, 1, 20, 12, 6, tzinfo=UTC), **common)
        plan = build_plan(base_at=datetime(2030, 1, 20, 13, 0, tzinfo=UTC), **common)
        self.assertEqual("2030-01-20T13:00:00.000Z", plan["scenarios"]["duration_below_threshold"]["rendered_at"])


if __name__ == "__main__":
    unittest.main()
