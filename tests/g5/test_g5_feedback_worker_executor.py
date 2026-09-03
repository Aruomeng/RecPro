from __future__ import annotations

import unittest
from datetime import UTC, datetime
from uuid import UUID

from backend.app.feedback.domain.public import (
    BehaviorAppendCommand,
    FeedbackCommand,
    ImpressionCommand,
)
from backend.app.shared_kernel.contracts.enums import (
    BehaviorEventType,
    FeedbackType,
    NegativeReasonCode,
)
from scripts.execute_g5_feedback_worker_plan import (
    FINAL_DELTAS,
    INTERACTION_DELTAS,
    _assert_delta,
    build_commands,
)
from scripts.build_g5_feedback_http_plan import (
    _replay_projection,
    canonical,
    expected_final_deltas,
    require_interaction_after_latest_behavior,
    sha256_bytes,
    target_snapshot_from_facts,
)


class G5FeedbackWorkerExecutorTests(unittest.TestCase):
    def test_full_replay_projection_counts_historical_logs_and_final_keys(self) -> None:
        facts = {
            "resource_tags": (
                {"tag_id": 5, "weight": 1.0, "confidence": 1.0},
                {"tag_id": 6, "weight": 1.0, "confidence": 1.0},
            ),
            "replay_events": (
                {
                    "event_id": 1,
                    "event_uuid": "event-1",
                    "event_type": "VIEW_RESOURCE",
                    "resource_id": 10,
                    "occurred_at": "2025-01-01T00:00:00Z",
                    "reason_code": None,
                },
                {
                    "event_id": 2,
                    "event_uuid": "event-2",
                    "event_type": "FAVORITE_RESOURCE",
                    "resource_id": 11,
                    "occurred_at": "2030-01-20T14:59:00Z",
                    "reason_code": None,
                },
            ),
            "replay_resource_tags": {
                "10": [{"tag_id": 1, "weight": 1.0, "confidence": 1.0}],
                "11": [{"tag_id": 3, "weight": 1.0, "confidence": 1.0}],
                "128": [
                    {"tag_id": 5, "weight": 1.0, "confidence": 1.0},
                    {"tag_id": 6, "weight": 1.0, "confidence": 1.0},
                ],
            },
            "replay_log_source_event_ids": (1,),
            "user_interest_tag_ids": (1, 3),
            "user_negative_preference_keys": (),
        }
        payload = {
            "user_id": 1001,
            "resource_id": 128,
            "impression_uuid": "762b46fa-ccf3-5fe5-96d9-072319e2cb75",
            "feedback_uuid": "11fdc777-a3cd-56cd-b0d3-60072fb3af4c",
            "behavior_uuid": "adedc97f-c97f-59f3-9b46-1c29025c0d0a",
            "impression_rendered_at": "2030-01-20T15:00:00Z",
            "feedback_occurred_at": "2030-01-20T15:00:02Z",
            "behavior_occurred_at": "2030-01-20T15:01:00Z",
        }
        projection = _replay_projection(facts, interaction_payload=payload)
        self.assertEqual(4, projection["feedback_replay_event_count"])
        self.assertEqual(5, projection["behavior_replay_event_count"])
        self.assertEqual([1, 3, 5, 6], projection["final_interest_tag_ids"])
        self.assertEqual(
            [
                {"tag_id": 5, "reason_code": "TOPIC_NOT_INTERESTED"},
                {"tag_id": 6, "reason_code": "TOPIC_NOT_INTERESTED"},
            ],
            projection["final_negative_preference_keys"],
        )
        # Existing event 2 plus impression/feedback are missing on the first
        # replay; the direct click is missing on the second replay.
        self.assertEqual(4, projection["profile_change_log_delta"])
        facts["replay_projection"] = projection
        deltas = expected_final_deltas(facts)
        self.assertEqual(4, deltas["profile_change_log"])
        self.assertEqual(2, deltas["user_interest_tag"])
        self.assertEqual(2, deltas["user_negative_preference"])

    def test_new_interaction_must_follow_latest_database_utc_behavior(self) -> None:
        facts = {"latest_behavior_at": "2030-01-20T12:06:00"}
        require_interaction_after_latest_behavior(
            facts,
            impression_rendered_at=datetime(2030, 1, 20, 13, 0, tzinfo=UTC),
        )
        with self.assertRaises(ValueError):
            require_interaction_after_latest_behavior(
                facts,
                impression_rendered_at=datetime(2030, 1, 20, 12, 6, tzinfo=UTC),
            )

    def test_bounded_deltas_sum_to_approved_change_budget(self) -> None:
        self.assertEqual(26, sum(FINAL_DELTAS.values()))
        self.assertEqual(11, sum(INTERACTION_DELTAS.values()))

    def test_delta_assertion_rejects_drift(self) -> None:
        _assert_delta({"a": 4}, {"a": 5}, {"a": 1})
        with self.assertRaises(ValueError):
            _assert_delta({"a": 4}, {"a": 6}, {"a": 1})

    def test_target_snapshot_hash_freezes_all_reviewed_target_facts(self) -> None:
        facts = {
            "task": {"id": "task"},
            "record": {"id": 24},
            "item": {"id": 129, "resource_id": 6850},
            "resource_tags": ({"tag_id": 102, "weight": 0.8, "confidence": 0.95, "source": "IMPORT"},),
            "resource_states": (),
            "outbox_statuses": {"DONE": 25},
            "uuid_absence": {"impression_uuid": 0, "feedback_uuid": 0, "behavior_uuid": 0},
            "latest_behavior_at": "2030-01-20T12:00:00",
            "user_profile_count": 1,
            "user_interest_tag_ids": (102,),
            "user_negative_preference_keys": ({"tag_id": 102, "reason_code": "TOPIC_NOT_INTERESTED"},),
        }
        snapshot = target_snapshot_from_facts(facts)
        self.assertNotIn("user_profile_count", snapshot)
        baseline_hash = sha256_bytes(canonical(snapshot))
        facts["resource_tags"] = tuple((*facts["resource_tags"], {"tag_id": 8463, "weight": 0.9, "confidence": 0.9, "source": "IMPORT"}))
        self.assertNotEqual(baseline_hash, sha256_bytes(canonical(target_snapshot_from_facts(facts))))

    def test_projection_deltas_count_only_new_profile_keys(self) -> None:
        facts = {
            "resource_tags": (
                {"tag_id": 102},
                {"tag_id": 6178},
                {"tag_id": 6962},
                {"tag_id": 7885},
                {"tag_id": 8463},
            ),
            "user_interest_tag_ids": (1, 2, 3, 4, 5, 6, 102, 8463),
            "user_negative_preference_keys": tuple(
                {"tag_id": tag_id, "reason_code": "TOPIC_NOT_INTERESTED"}
                for tag_id in (1, 2, 3, 4, 5, 6, 102, 8463)
            ),
        }
        deltas = expected_final_deltas(facts)
        self.assertEqual(3, deltas["user_interest_tag"])
        self.assertEqual(3, deltas["user_negative_preference"])
        self.assertEqual(28, sum(deltas.values()))

    def test_first_profile_projection_is_created_for_a_new_reader(self) -> None:
        facts = {
            "resource_tags": ({"tag_id": 102},),
            "user_profile_count": 0,
            "user_interest_tag_ids": (),
            "user_negative_preference_keys": (),
        }
        deltas = expected_final_deltas(facts)
        self.assertEqual(1, deltas["user_profile"])
        self.assertEqual(1, deltas["user_interest_tag"])
        self.assertEqual(1, deltas["user_negative_preference"])

    def test_multiple_profile_projection_rows_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            expected_final_deltas({"resource_tags": (), "user_profile_count": 2})

    def test_build_commands_freezes_the_three_interaction_boundaries(self) -> None:
        payload = {
            "impression_uuid": "762b46fa-ccf3-5fe5-96d9-072319e2cb75",
            "feedback_uuid": "11fdc777-a3cd-56cd-b0d3-60072fb3af4c",
            "behavior_uuid": "adedc97f-c97f-59f3-9b46-1c29025c0d0a",
            "behavior_session_id": "3c4da2da-0317-53ba-9446-34fe1a331381",
            "recommendation_task_id": "b476b901-b78e-5c3e-afd9-6fc880f20623",
            "recommendation_item_id": 128,
            "user_id": 1001,
            "resource_id": 6452,
            "position": 1,
            "impression_rendered_at": "2026-08-12T00:55:00Z",
            "impression_visible_started_at": "2026-08-12T00:55:00Z",
            "impression_visible_ms": 1500,
            "impression_max_visible_ratio": 0.8,
            "feedback_occurred_at": "2026-08-12T00:55:00Z",
            "behavior_occurred_at": "2026-08-12T00:56:00Z",
            "query_text": "多智能体系统与智慧图书馆",
            "direct_behavior_dwell_ms": 2000,
            "direct_behavior_visible_ratio": 0.9,
        }
        impression, feedback, behavior = build_commands(payload)
        self.assertIsInstance(impression, ImpressionCommand)
        self.assertIsInstance(feedback, FeedbackCommand)
        self.assertIsInstance(behavior, BehaviorAppendCommand)
        self.assertEqual(UUID(payload["impression_uuid"]), impression.impression_uuid)
        self.assertEqual(FeedbackType.NOT_INTERESTED, feedback.feedback_type)
        self.assertEqual(NegativeReasonCode.TOPIC_NOT_INTERESTED, feedback.reason_code)
        self.assertEqual(BehaviorEventType.CLICK_RECOMMENDATION, behavior.event_type)
        self.assertTrue(behavior.enqueue_profile_update)
        self.assertEqual(UUID(payload["recommendation_task_id"]), behavior.task_id)
        self.assertEqual(datetime(2026, 8, 12, 0, 56, tzinfo=UTC), behavior.occurred_at)


if __name__ == "__main__":
    unittest.main()
