from __future__ import annotations

import unittest

from scripts.verify_g8_release_preflight import (
    inspect_fail_closed_defaults,
    validate_run_id,
)


class ReleasePreflightTest(unittest.TestCase):
    def test_run_id_is_safe_and_distinguishes_path_traversal(self) -> None:
        self.assertEqual("g8-release-preflight-20260812-001", validate_run_id("g8-release-preflight-20260812-001"))
        with self.assertRaises(ValueError):
            validate_run_id("../overwrite")
        with self.assertRaises(ValueError):
            validate_run_id("a")

    def test_current_default_composition_is_fail_closed(self) -> None:
        report = inspect_fail_closed_defaults()
        self.assertEqual("PASS", report["status"])
        self.assertEqual([], report["issues"])


if __name__ == "__main__":
    unittest.main()
