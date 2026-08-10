from __future__ import annotations

import unittest

from scripts.verify_experiment_freeze import (
    PROJECT_ROOT,
    build_preflight_report,
    validate_run_id,
)


class ExperimentFreezePreflightTest(unittest.TestCase):
    def test_current_fixture_is_reproducible_but_not_paper_confirmatory(self) -> None:
        report = build_preflight_report(
            protocol_path=PROJECT_ROOT / "docs" / "experiment_protocol.md",
            manifest_path=PROJECT_ROOT / "contracts" / "data" / "g2" / "dataset_manifest.json",
            git_status="",
            git_commit="test-commit",
        )
        self.assertEqual("PASS_WITH_BLOCKERS", report["status"])
        self.assertFalse(report["paper_confirmation_ready"])
        self.assertEqual("synthetic", report["dataset"]["source_kind"])
        codes = {item["code"] for item in report["blockers"]}
        self.assertIn("DEMO_FIXTURE", codes)
        self.assertIn("F2_SPLIT_MISSING", codes)
        self.assertEqual(0, report["safety"]["expected_delete_count"])
        self.assertEqual(0, report["safety"]["actual_delete_count"])

    def test_dirty_worktree_is_a_formal_run_blocker(self) -> None:
        report = build_preflight_report(
            protocol_path=PROJECT_ROOT / "docs" / "experiment_protocol.md",
            manifest_path=PROJECT_ROOT / "contracts" / "data" / "g2" / "dataset_manifest.json",
            git_status=" M backend/app/config.py",
            git_commit="test-commit",
        )
        self.assertIn(
            "WORKTREE_DIRTY",
            {item["code"] for item in report["blockers"]},
        )
        self.assertFalse(report["freeze"]["F3_configuration"])

    def test_run_id_is_safe_and_repo_relative_inputs_are_expected(self) -> None:
        self.assertEqual("freeze-20260810-001", validate_run_id("freeze-20260810-001"))
        with self.assertRaises(ValueError):
            validate_run_id("../overwrite")
        self.assertTrue((PROJECT_ROOT / "docs" / "experiment_protocol.md").is_file())


if __name__ == "__main__":
    unittest.main()
