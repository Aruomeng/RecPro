from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.build_g8_browser_scenario_plan import build_plan, canonical
from scripts.verify_g8_browser_scenario_plan import validate_plan


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BASELINE = PROJECT_ROOT / "artifacts/verification/g4/g4-browser-uuidv5-replay-after-20260814-001/readonly.json"


class BrowserScenarioPlanTests(unittest.TestCase):
    def test_plan_freezes_six_unique_scenarios_and_zero_destructive_budget(self) -> None:
        with patch("scripts.build_g8_browser_scenario_plan.require_clean_worktree"):
            plan = build_plan(
                run_id="g8-browser-test-plan-001",
                baseline_path=BASELINE,
                compose_project="recpro-g2-tianyuhang-20260809a",
            )
        self.assertEqual(plan["scenario_ids"], [
            "cold_user_guided", "clear_user_recommendation", "topic_user_explanation",
            "reading_path_clarification", "negative_feedback_adjustment", "degraded_dependency_path",
        ])
        self.assertEqual(len({item["request"]["request_id"] for item in plan["scenarios"]}), 6)
        reading_path = next(
            item
            for item in plan["scenarios"]
            if item["scenario_id"] == "reading_path_clarification"
        )
        self.assertEqual(reading_path["expected"]["status"], "COMPLETED")
        self.assertEqual(reading_path["expected"]["delivery_strategy"], "DIRECT")
        self.assertEqual(reading_path["expected"]["minimum_items"], 6)
        self.assertEqual(plan["aggregate_budget"]["max_outbox_claims"], 0)
        self.assertFalse(plan["safety_assertions"]["business_writes_authorized"])
        unsigned = dict(plan)
        plan_hash = unsigned.pop("plan_hash")
        self.assertEqual(hashlib.sha256(canonical(unsigned)).hexdigest(), plan_hash)

    def test_tampering_with_scenario_input_is_rejected(self) -> None:
        with patch("scripts.build_g8_browser_scenario_plan.require_clean_worktree"):
            plan = build_plan(
                run_id="g8-browser-test-plan-002",
                baseline_path=BASELINE,
                compose_project="recpro-g2-tianyuhang-20260809a",
            )
        plan["scenarios"][0]["request"]["input_text"] = "tampered"
        with self.assertRaisesRegex(ValueError, "canonical hash"):
            validate_plan(plan, expected_commit=None)

    def test_fixture_and_replay_invariants_are_enforced(self) -> None:
        with patch("scripts.build_g8_browser_scenario_plan.require_clean_worktree"):
            plan = build_plan(
                run_id="g8-browser-test-plan-003",
                baseline_path=BASELINE,
                compose_project="recpro-g2-tianyuhang-20260809a",
            )
        plan["plan_hash"] = hashlib.sha256(canonical({key: value for key, value in plan.items() if key != "plan_hash"})).hexdigest()
        plan["scenarios"][1]["fixture_user"] = plan["scenarios"][0]["fixture_user"]
        plan["plan_hash"] = hashlib.sha256(canonical({key: value for key, value in plan.items() if key != "plan_hash"})).hexdigest()
        with self.assertRaisesRegex(ValueError, "six distinct fixture"):
            validate_plan(plan, expected_commit=None)


if __name__ == "__main__":
    unittest.main()
