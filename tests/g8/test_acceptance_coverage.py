from __future__ import annotations

import unittest

from scripts.verify_g8_acceptance_coverage import (
    CASE_COVERAGE,
    PROJECT_ROOT,
    build_coverage_report,
    parse_acceptance_matrix,
    validate_run_id,
)


class AcceptanceCoverageAuditTest(unittest.TestCase):
    def test_matrix_and_mapping_cover_exactly_a01_to_a25(self) -> None:
        rows = parse_acceptance_matrix(PROJECT_ROOT / "docs" / "acceptance_matrix.md")
        case_ids = [item["case_id"] for item in rows]
        self.assertEqual([f"A{index:02d}" for index in range(1, 26)], case_ids)
        self.assertEqual(case_ids, list(CASE_COVERAGE))

    def test_report_keeps_offline_inventory_separate_from_final_revalidation(self) -> None:
        report = build_coverage_report(
            matrix_path=PROJECT_ROOT / "docs" / "acceptance_matrix.md",
            git_status="",
            git_commit="test-commit",
        )
        self.assertEqual("g8-acceptance-coverage-audit-v1", report["schema_version"])
        self.assertEqual("PASS_WITH_BLOCKERS", report["status"])
        self.assertFalse(report["release_candidate_ready"])
        self.assertEqual(25, report["coverage_counts"]["total"])
        self.assertEqual(25, report["coverage_counts"]["final_revalidation_pending"])
        self.assertEqual([], [item["case_id"] for item in report["cases"] if not item["mapping_valid"]])
        self.assertEqual(0, report["safety"]["database_reads"])
        self.assertEqual(0, report["safety"]["database_writes"])
        self.assertEqual(0, report["safety"]["files_deleted"])
        self.assertIn(
            "A01_A25_FINAL_REVALIDATION_PENDING",
            {item["code"] for item in report["blockers"]},
        )

    def test_run_id_is_safe_and_rejects_path_traversal(self) -> None:
        self.assertEqual("a-coverage-20260812-001", validate_run_id("a-coverage-20260812-001"))
        with self.assertRaises(ValueError):
            validate_run_id("../overwrite")


if __name__ == "__main__":
    unittest.main()

