from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts.build_current_synthetic_profile_demo_change_plan import INPUTS, _canonical
from scripts.execute_current_synthetic_profile_demo_change_plan import PROJECT_ROOT, validate


class CurrentSyntheticProfileDemoExecutorTests(unittest.TestCase):
    def _plan(self) -> dict[str, object]:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, check=True, capture_output=True, text=True).stdout.strip()
        return {
            "schema_version": "current-synthetic-profile-demo-change-plan-v1",
            "plan_id": "test-profile-plan",
            "git_commit": commit,
            "classification": "S2_CONTROLLED_PROFILE_DEMO",
            "mode": "APPLY",
            "intent": {"target": {"user_id": 1002, "synthetic_user_id": "synthetic-u-0001"}},
            "projection_preview": {"expected_deltas": {
                "user_behavior_event": 16, "profile_update_outbox": 1, "profile_replay_run": 1,
                "profile_change_log": 16, "domain_state_transition": 3, "user_profile": 0,
                "user_interest_tag": 0, "user_negative_preference": 0,
            }},
            "safety": {"database_deletions": 0, "file_deletions": 0, "neo4j_writes": 0, "chroma_writes": 0, "deepseek_requests": 0, "recommendation_tasks": 0},
            "input_hashes": {item: sha256((PROJECT_ROOT / item).read_bytes()).hexdigest() for item in INPUTS},
        }

    def _write(self, plan: dict[str, object]) -> Path:
        unsigned = dict(plan)
        plan["plan_hash"] = sha256(_canonical(unsigned)).hexdigest()
        path = Path(tempfile.mkdtemp()) / "plan.json"
        path.write_text(json.dumps(plan), encoding="utf-8")
        return path

    def test_fixed_profile_demo_boundary_validates_without_database(self) -> None:
        plan = self._plan(); path = self._write(plan)
        result = validate(path, plan_id="test-profile-plan", plan_hash=str(plan["plan_hash"]))
        self.assertEqual("S2_CONTROLLED_PROFILE_DEMO", result["classification"])

    def test_rejects_any_model_budget_before_database_connection(self) -> None:
        plan = self._plan()
        safety = dict(plan["safety"]); safety["deepseek_requests"] = 1; plan["safety"] = safety
        path = self._write(plan)
        with self.assertRaisesRegex(ValueError, "safety budget"):
            validate(path, plan_id="test-profile-plan", plan_hash=str(plan["plan_hash"]))


if __name__ == "__main__":
    unittest.main()
