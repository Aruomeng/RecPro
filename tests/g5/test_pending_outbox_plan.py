from __future__ import annotations

import hashlib
import unittest

from scripts.build_g5_feedback_http_plan import canonical
from scripts.build_g5_pending_outbox_plan import parse_outbox_ids
from scripts.execute_g5_pending_outbox_plan import extract_outbox_ids


class PendingOutboxPlanTests(unittest.TestCase):
    def test_parse_outbox_ids_is_sorted_and_bounded(self) -> None:
        self.assertEqual((47, 48), parse_outbox_ids("48,47"))
        for unsafe in ("0", "47,47", ","):
            with self.subTest(unsafe=unsafe), self.assertRaises((ValueError, TypeError)):
                parse_outbox_ids(unsafe)

    def test_executor_extracts_only_exact_sorted_target(self) -> None:
        plan = {
            "targets": [
                {"identifier": "recpro.profile_update_outbox#47,48"},
                {"identifier": "recpro.profile_replay_run"},
            ]
        }
        self.assertEqual((47, 48), extract_outbox_ids(plan))
        plan["targets"][0]["identifier"] = "recpro.profile_update_outbox#48,47"
        with self.assertRaises(ValueError):
            extract_outbox_ids(plan)

    def test_plan_hash_changes_when_exact_target_changes(self) -> None:
        plan = {"targets": [{"identifier": "recpro.profile_update_outbox#47,48"}]}
        first = hashlib.sha256(canonical(plan)).hexdigest()
        plan["targets"][0]["identifier"] = "recpro.profile_update_outbox#47"
        self.assertNotEqual(first, hashlib.sha256(canonical(plan)).hexdigest())


if __name__ == "__main__":
    unittest.main()
