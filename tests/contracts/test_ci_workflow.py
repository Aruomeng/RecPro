from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = ROOT / ".github/workflows/g0-quality.yml"
CHECKOUT_ACTION = "actions/checkout@11d5960a326750d5838078e36cf38b85af677262"
SETUP_PYTHON_ACTION = "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065"


class G0WorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow: dict[str, Any] = yaml.load(
            WORKFLOW_PATH.read_text(encoding="utf-8"),
            Loader=yaml.BaseLoader,
        )
        cls.steps = cls.workflow["jobs"]["verify-g0"]["steps"]

    def test_workflow_is_valid_mapping_with_expected_triggers(self) -> None:
        self.assertIsInstance(self.workflow, dict)
        self.assertEqual({"push", "pull_request"}, set(self.workflow["on"]))

    def test_checkout_fetches_history_for_committed_change_scan(self) -> None:
        checkout = next(
            step for step in self.steps if step.get("uses") == CHECKOUT_ACTION
        )
        self.assertEqual("0", checkout["with"]["fetch-depth"])

    def test_third_party_actions_are_pinned_to_full_commits(self) -> None:
        action_refs = {
            step["uses"] for step in self.steps if "uses" in step
        }
        self.assertEqual({CHECKOUT_ACTION, SETUP_PYTHON_ACTION}, action_refs)

    def test_ci_uses_frozen_g0_dependency_file(self) -> None:
        commands = "\n".join(str(step.get("run", "")) for step in self.steps)
        self.assertIn("backend/requirements-g0.lock", commands)
        self.assertIn("--require-hashes", commands)

    def test_committed_change_scan_is_mandatory(self) -> None:
        history_scan = next(
            step
            for step in self.steps
            if step.get("name") == "Reject committed file deletion or rename"
        )
        self.assertIn("--base-ref", history_scan["run"])
        self.assertNotIn("continue-on-error", history_scan)


if __name__ == "__main__":
    unittest.main()
