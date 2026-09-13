from __future__ import annotations

import unittest

from scripts.stage3_background_planning_change_plan import (
    _FixturePlanningModel,
    run_dual_workspace_probe,
)


class Stage3BackgroundPlanningChangePlanTests(unittest.TestCase):
    def test_fixture_exercises_guest_and_formal_reader_without_persistence(self) -> None:
        result = run_dual_workspace_probe(
            model=_FixturePlanningModel(),
            run_id="stage3-unit-fixture-001",
            commit="0" * 40,
            timeout_seconds=5,
        )

        self.assertEqual(2, result["external_requests"])
        self.assertEqual(0, result["database_connections"])
        self.assertEqual(0, result["database_writes"])
        self.assertEqual(0, result["neo4j_writes"])
        self.assertEqual(0, result["chroma_writes"])
        contexts = result["model_contexts"]
        self.assertEqual(["guest", "authenticated"], [item["mode"] for item in contexts])
        self.assertFalse(contexts[0]["profile_present"])
        self.assertTrue(contexts[1]["profile_present"])
        self.assertNotIn("user_id", contexts[1]["profile_keys"])
        for workspace in result["workspaces"]:
            self.assertEqual("PLANNED", workspace["status"])
            self.assertEqual(1, workspace["model_requests"])
            self.assertFalse(workspace["fallback_used"])
            self.assertTrue(workspace["decision_id"])
            self.assertIn("AGENT_STARTED", workspace["planning_event_types"])
            self.assertIn("AGENT_COMPLETED", workspace["planning_event_types"])


if __name__ == "__main__":
    unittest.main()
