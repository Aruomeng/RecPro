from __future__ import annotations

import unittest

from scripts.build_g8_final_revalidation_plan import (
    PROJECT_ROOT,
    build_plan,
    canonical_json,
    sha256_bytes,
    validate_plan,
    validate_run_id,
)


class FinalRevalidationPlanTest(unittest.TestCase):
    def test_plan_freezes_all_cases_and_browser_boundaries(self) -> None:
        plan = build_plan(
            run_id="g8-final-revalidation-plan-test-001",
            git_commit="a" * 40,
        )
        self.assertEqual([], validate_plan(plan))
        self.assertEqual("READ_ONLY", plan["mode"])
        self.assertEqual([f"A{index:02d}" for index in range(1, 26)], plan["matrix"]["case_ids"])
        self.assertEqual(25, len(plan["cases"]))
        self.assertEqual(6, len(plan["browser_scenarios"]))
        self.assertEqual("PENDING", {item["state"] for item in plan["browser_scenarios"]}.pop())
        self.assertTrue(
            all(item["write_policy"] == "REQUIRES_SEPARATE_CHANGE_PLAN" for item in plan["browser_scenarios"])
        )

    def test_plan_hash_is_content_addressed_and_safety_is_zero(self) -> None:
        plan = build_plan(
            run_id="g8-final-revalidation-plan-test-002",
            git_commit="b" * 40,
        )
        unsigned = dict(plan)
        plan_hash = unsigned.pop("plan_hash")
        self.assertEqual(plan_hash, sha256_bytes(canonical_json(unsigned)))
        self.assertEqual(0, plan["safety_assertions"]["database_writes"])
        self.assertEqual(0, plan["safety_assertions"]["outbox_claims"])
        self.assertFalse(plan["safety_assertions"]["business_post_authorization"])
        self.assertEqual("docs/acceptance_matrix.md", plan["matrix"]["path"])
        self.assertTrue((PROJECT_ROOT / plan["matrix"]["path"]).is_file())

    def test_run_id_rejects_path_traversal(self) -> None:
        self.assertEqual("g8-final-revalidation-plan-20260812-001", validate_run_id("g8-final-revalidation-plan-20260812-001"))
        with self.assertRaises(ValueError):
            validate_run_id("../overwrite")


if __name__ == "__main__":
    unittest.main()
