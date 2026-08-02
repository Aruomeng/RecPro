from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from scripts.validate_contracts import (
    extract_change_plan_policy_example,
    validate_change_plan_contract,
    validate_change_plan_semantics,
)


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "contracts/safety/change-plan.schema.json"
EXAMPLE_PATH = ROOT / "contracts/safety/examples/change-plan-dry-run.json"


class ChangePlanContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
        cls.validator = Draft202012Validator(
            cls.schema,
            format_checker=FormatChecker(),
        )

    def test_valid_dry_run_example_and_policy_block_match_schema(self) -> None:
        self.assertEqual([], list(self.validator.iter_errors(self.example)))

        policy_example, extraction_issues = extract_change_plan_policy_example(ROOT)
        self.assertEqual([], extraction_issues)
        self.assertEqual(self.example, policy_example)
        self.assertEqual([], list(self.validator.iter_errors(policy_example)))

        documents = {
            "contracts/safety/change-plan.schema.json": self.schema,
            "contracts/safety/examples/change-plan-dry-run.json": self.example,
        }
        self.assertEqual([], validate_change_plan_contract(ROOT, documents))

    def test_invalid_uuid_is_rejected_by_format_checker(self) -> None:
        invalid = deepcopy(self.example)
        invalid["plan_id"] = "chg-20260802-not-a-uuid"

        errors = list(self.validator.iter_errors(invalid))
        self.assertTrue(
            any(
                list(error.absolute_path) == ["plan_id"]
                and error.validator == "format"
                for error in errors
            ),
            errors,
        )

    def test_datetime_without_timezone_is_rejected_by_format_checker(self) -> None:
        invalid = deepcopy(self.example)
        invalid["created_at"] = "2026-08-02T00:00:00"

        errors = list(self.validator.iter_errors(invalid))
        self.assertTrue(
            any(
                list(error.absolute_path) == ["created_at"]
                and error.validator in {"format", "pattern"}
                for error in errors
            ),
            errors,
        )

    def test_expected_count_cannot_decrease(self) -> None:
        invalid = deepcopy(self.example)
        invalid["targets"][0]["expected_before_count"] = 120
        invalid["targets"][0]["expected_after_min_count"] = 0
        codes = {
            issue.code for issue in validate_change_plan_semantics(invalid)
        }
        self.assertIn("CHANGE_PLAN_COUNT_DECREASE_FORBIDDEN", codes)

    def test_expected_increase_cannot_exceed_max_changes(self) -> None:
        invalid = deepcopy(self.example)
        invalid["max_changes"] = 0
        codes = {
            issue.code for issue in validate_change_plan_semantics(invalid)
        }
        self.assertIn("CHANGE_PLAN_MAX_CHANGES_EXCEEDED", codes)

    def test_read_only_classification_cannot_append(self) -> None:
        invalid = deepcopy(self.example)
        invalid["classification"] = "S0_READ_ONLY"
        codes = {
            issue.code for issue in validate_change_plan_semantics(invalid)
        }
        self.assertIn("CHANGE_PLAN_CLASSIFICATION_OPERATION_MISMATCH", codes)


if __name__ == "__main__":
    unittest.main()
