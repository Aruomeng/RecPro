from __future__ import annotations

import unittest

from scripts.execute_g7_recommendation_post import validate_exact_replay


class RecommendationReplayExecutorTest(unittest.TestCase):
    def test_exact_replay_requires_same_task_and_zero_count_delta(self) -> None:
        validate_exact_replay(
            first_task_id="task-1",
            replay_status_code=200,
            replay_header="true",
            replay_body={"task_id": "task-1"},
            after_first_post={"recommendation_task": 25, "recommendation_item": 137},
            after_replay_post={"recommendation_task": 25, "recommendation_item": 137},
        )

    def test_exact_replay_rejects_identity_or_count_drift(self) -> None:
        common = {
            "first_task_id": "task-1",
            "replay_status_code": 200,
            "replay_header": "true",
            "replay_body": {"task_id": "task-1"},
            "after_first_post": {"recommendation_task": 25},
            "after_replay_post": {"recommendation_task": 25},
        }
        for change in (
            {"replay_status_code": 201},
            {"replay_header": "false"},
            {"replay_body": {"task_id": "task-2"}},
            {"after_replay_post": {"recommendation_task": 26}},
        ):
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                validate_exact_replay(**{**common, **change})


if __name__ == "__main__":
    unittest.main()
