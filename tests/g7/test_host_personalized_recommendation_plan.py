from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts.build_host_personalized_recommendation_plan import build


class HostPersonalizedRecommendationPlanTests(unittest.TestCase):
    def test_plan_binds_profile_v4_and_has_zero_model_budget(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            baseline = Path(temporary) / "baseline.json"
            baseline.write_text(json.dumps({
                "status": "PASS", "can_recommend": True, "profile": {"profile_version": 4},
                "before_counts": {
                    "recommendation_task": 1, "recommendation_task_transition": 1,
                    "recommendation_candidate": 1, "recommendation_record": 1,
                    "recommendation_item": 1, "recommendation_item_explanation": 1,
                    "recommendation_policy_decision": 1, "recommendation_trace": 1,
                },
            }), encoding="utf-8")
            plan = build(baseline_path=baseline)
        self.assertEqual(1002, plan["request"]["user_id"])
        self.assertEqual(4, plan["baseline"]["profile_version"])
        self.assertEqual(0, plan["safety"]["deepseek_requests"])
        self.assertEqual(37, plan["max_row_increase"])


if __name__ == "__main__":
    unittest.main()
