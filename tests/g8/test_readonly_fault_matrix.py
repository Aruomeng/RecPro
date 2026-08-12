from __future__ import annotations

import unittest

from scripts.build_g8_final_revalidation_plan import build_plan
from scripts.verify_g8_final_revalidation_plan import (
    RUNTIME_EVIDENCE_SCHEMA_PATH,
    _validate_instance,
)
from scripts.verify_g8_readonly_fault_matrix import (
    READ_ONLY_CASE_IDS,
    _module_from_test_ref,
    build_runtime_evidence,
    selected_cases,
)


class ReadOnlyFaultMatrixTest(unittest.TestCase):
    def setUp(self) -> None:
        self.plan = build_plan(
            run_id="g8-readonly-fault-matrix-plan-test-001",
            git_commit="a" * 40,
        )

    def test_frozen_selection_contains_exactly_17_authorization_free_cases(self) -> None:
        cases = selected_cases(self.plan)
        self.assertEqual(list(READ_ONLY_CASE_IDS), [case["case_id"] for case in cases])
        self.assertEqual(17, len(cases))
        self.assertEqual(13, len({module for case in cases for module in case["modules"]}))

    def test_test_reference_conversion_stays_inside_tests(self) -> None:
        self.assertEqual(
            "tests.g4.test_orchestrator",
            _module_from_test_ref(
                "tests/g4/test_orchestrator.py::test_unclear_path_stops_at_guided_before_recall"
            ),
        )
        with self.assertRaises(ValueError):
            _module_from_test_ref("../tests/test_escape.py::test_escape")

    def test_runtime_evidence_promotes_only_read_only_cases(self) -> None:
        evidence = build_runtime_evidence(
            plan=self.plan,
            git_commit="a" * 40,
            fault_matrix_path="artifacts/verification/g8/test/readonly-fault-matrix.json",
            fault_matrix_sha256="b" * 64,
        )
        self.assertEqual([], _validate_instance(RUNTIME_EVIDENCE_SCHEMA_PATH, evidence))
        passed = [case["case_id"] for case in evidence["cases"] if case["status"] == "PASS"]
        pending = [case for case in evidence["cases"] if case["status"] == "PENDING"]
        self.assertEqual(list(READ_ONLY_CASE_IDS), passed)
        self.assertEqual(8, len(pending))
        self.assertTrue(all(case["change_plan"] is None for case in evidence["cases"]))


if __name__ == "__main__":
    unittest.main()
