from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / "plans/agent-workspace-audit-20260820-001.json"
SUCCESSOR = ROOT / "plans/agent-workspace-audit-successor.json"
SCHEMA = ROOT / "contracts/safety/change-plan.schema.json"


class AgentWorkspaceAuditPlanTests(unittest.TestCase):
    def test_plan_is_schema_valid_canonical_and_zero_destructive(self) -> None:
        plan = json.loads(PLAN.read_text(encoding="utf-8"))
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(plan)
        unsigned = dict(plan)
        expected = unsigned.pop("plan_hash")
        canonical = json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        self.assertEqual(expected, hashlib.sha256(canonical).hexdigest())
        self.assertEqual(0, plan["safety_assertions"]["file_deletions"])
        self.assertEqual(0, plan["safety_assertions"]["database_physical_deletions"])
        self.assertEqual(17, plan["max_changes"])
        self.assertTrue(all(target["operation"] in {"CREATE", "APPEND"} for target in plan["targets"]))

    def test_plan_freezes_demo_identity_and_zero_llm_budget(self) -> None:
        plan = json.loads(PLAN.read_text(encoding="utf-8"))
        conditions = "\n".join(plan["preconditions"])
        self.assertIn("demo user_id is exactly 1001", conditions)
        self.assertIn("DeepSeek request budget is exactly 0", conditions)
        self.assertIn("no compensating removal is allowed", conditions)

    def test_successor_is_schema_valid_and_binds_the_exact_runtime_inputs(self) -> None:
        plan = json.loads(SUCCESSOR.read_text(encoding="utf-8"))
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(plan)
        unsigned = dict(plan)
        expected = unsigned.pop("plan_hash")
        canonical = json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        self.assertEqual(expected, hashlib.sha256(canonical).hexdigest())
        self.assertEqual("f670b88adb1d315fb22969daa5c2f6e795a8054a", plan["git_commit"])
        self.assertEqual("APPLY", plan["mode"])
        self.assertEqual(7, len(plan["input_hashes"]))
        self.assertEqual(17, plan["max_changes"])
        self.assertEqual(0, plan["safety_assertions"]["database_physical_deletions"])


if __name__ == "__main__":
    unittest.main()
