from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts.build_synthetic_demo_behavior_change_plan import INPUTS, _canonical
from scripts.execute_synthetic_demo_behavior_change_plan import PROJECT_ROOT, validate


class SyntheticDemoBehaviorExecutorTests(unittest.TestCase):
    def _plan(self) -> dict[str, object]:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, check=True,
            capture_output=True, text=True,
        ).stdout.strip()
        return {
            "schema_version": "synthetic-demo-behavior-change-plan-v1",
            "plan_id": "test-plan",
            "git_commit": commit,
            "classification": "S1_APPEND",
            "mode": "APPLY",
            "max_changes": 16,
            "target": {"user_id": 1001, "synthetic_user_id": "synthetic-u-0001"},
            "targets": [{
                "kind": "MYSQL",
                "identifier": "recpro.user_behavior_event:synthetic-demo-20260901",
                "operation": "APPEND",
                "rows": 16,
            }],
            "safety": {
                "database_deletions": 0,
                "file_deletions": 0,
                "profile_outbox_rows": 0,
                "profile_updates": 0,
                "neo4j_writes": 0,
                "chroma_writes": 0,
                "deepseek_requests": 0,
            },
            "input_hashes": {
                item: sha256((PROJECT_ROOT / item).read_bytes()).hexdigest()
                for item in INPUTS
            },
        }

    def _write(self, plan: dict[str, object]) -> Path:
        unsigned = dict(plan)
        plan["plan_hash"] = sha256(_canonical(unsigned)).hexdigest()
        root = Path(tempfile.mkdtemp())
        path = root / "plan.json"
        path.write_text(json.dumps(plan), encoding="utf-8")
        return path

    def test_exact_append_boundary_accepts_unchanged_plan_without_database(self) -> None:
        plan = self._plan()
        path = self._write(plan)
        actual = validate(path, plan_id="test-plan", plan_hash=str(plan["plan_hash"]))
        self.assertEqual("S1_APPEND", actual["classification"])

    def test_rejects_unexpected_target_before_any_database_connection(self) -> None:
        plan = self._plan()
        plan["target"] = {"user_id": 1002, "synthetic_user_id": "synthetic-u-0001"}
        path = self._write(plan)
        with self.assertRaisesRegex(ValueError, "fixed synthetic demo user"):
            validate(path, plan_id="test-plan", plan_hash=str(plan["plan_hash"]))

    def test_rejects_nonzero_secondary_side_effect_budget(self) -> None:
        plan = self._plan()
        safety = dict(plan["safety"])
        safety["profile_outbox_rows"] = 1
        plan["safety"] = safety
        path = self._write(plan)
        with self.assertRaisesRegex(ValueError, "safety budget"):
            validate(path, plan_id="test-plan", plan_hash=str(plan["plan_hash"]))


if __name__ == "__main__":
    unittest.main()
