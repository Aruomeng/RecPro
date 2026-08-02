from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = ROOT / ".github/workflows/g1-quality.yml"


class G1QualityWorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW_PATH.read_text(encoding="utf-8")
        cls.workflow = yaml.load(cls.text, Loader=yaml.BaseLoader)

    def test_actions_are_commit_pinned_and_permissions_are_read_only(self) -> None:
        self.assertEqual({"contents": "read"}, self.workflow["permissions"])
        steps = self.workflow["jobs"]["verify-g1-local"]["steps"]
        action_references = [step["uses"] for step in steps if "uses" in step]
        self.assertGreaterEqual(len(action_references), 3)
        for reference in action_references:
            with self.subTest(reference=reference):
                self.assertRegex(reference, r"@[0-9a-f]{40}$")
        checkout = next(step for step in steps if step.get("uses", "").startswith("actions/checkout@"))
        self.assertEqual("false", checkout["with"]["clean"])

    def test_fresh_locked_toolchains_and_all_python_locks_are_used(self) -> None:
        self.assertIn('node-version: "24.18.0"', self.text)
        for lock_name in (
            "requirements-g0.lock",
            "requirements-g1.lock",
            "requirements-g1-test.lock",
        ):
            self.assertIn(lock_name, self.text)
        self.assertIn("pip install --require-hashes", self.text)
        self.assertIn("npm ci --ignore-scripts --prefix frontend", self.text)

    def test_build_is_append_only_and_compose_check_is_configuration_only(self) -> None:
        self.assertRegex(
            self.text,
            re.compile(r"BUILD_RUN_ID=ci-\$\{\{ github\.run_id \}\}"),
        )
        self.assertIn("make compose-config", self.text)
        self.assertNotRegex(self.text, re.compile(r"docker\s+compose\s+up"))


if __name__ == "__main__":
    unittest.main()
