from __future__ import annotations

import unittest
from datetime import UTC, datetime

from backend.app.profile.replay import (
    BehaviorForReplay,
    ResourceTagEvidence,
    compute_profile_snapshot,
)


def at(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC).replace(tzinfo=None)


class ProfileReplayTests(unittest.TestCase):
    def test_as_of_boundary_excludes_future_facts_and_maps_only_topic_negative(self) -> None:
        events = (
            BehaviorForReplay(
                event_id=1,
                event_uuid="event-1",
                event_type="FAVORITE_RESOURCE",
                resource_id=10,
                occurred_at=at("2025-01-01T00:00:00"),
                reason_code=None,
                tags=(ResourceTagEvidence(7, 1.0, 1.0),),
            ),
            BehaviorForReplay(
                event_id=2,
                event_uuid="event-2",
                event_type="NOT_INTERESTED",
                resource_id=11,
                occurred_at=at("2025-02-01T00:00:00"),
                reason_code="TOPIC_NOT_INTERESTED",
                tags=(ResourceTagEvidence(8, 0.8, 0.5),),
            ),
            BehaviorForReplay(
                event_id=3,
                event_uuid="event-3",
                event_type="REJECT_RECOMMENDATION",
                resource_id=12,
                occurred_at=at("2025-03-01T00:00:00"),
                reason_code="TOO_ADVANCED",
                tags=(ResourceTagEvidence(9, 1.0, 1.0),),
            ),
        )
        snapshot = compute_profile_snapshot(
            user_id=1001,
            as_of=at("2025-02-01T00:00:00"),
            events=events,
        )
        self.assertEqual(2, snapshot.event_count)
        self.assertEqual(7, snapshot.recent_focus_tag_id)
        self.assertEqual((7,), tuple(item.tag_id for item in snapshot.interests))
        self.assertEqual((8,), tuple(item.tag_id for item in snapshot.negatives))
        self.assertEqual("TOPIC_NOT_INTERESTED", snapshot.negatives[0].reason_code)

    def test_replay_is_deterministic_under_input_reordering(self) -> None:
        first = BehaviorForReplay(
            event_id=2,
            event_uuid="event-2",
            event_type="VIEW_RESOURCE",
            resource_id=10,
            occurred_at=at("2025-01-02T00:00:00"),
            reason_code=None,
            tags=(ResourceTagEvidence(7, 0.8, 0.9),),
        )
        second = BehaviorForReplay(
            event_id=1,
            event_uuid="event-1",
            event_type="VIEW_RESOURCE",
            resource_id=10,
            occurred_at=at("2025-01-01T00:00:00"),
            reason_code=None,
            tags=(ResourceTagEvidence(7, 0.8, 0.9),),
        )
        left = compute_profile_snapshot(user_id=1001, as_of=at("2025-02-01T00:00:00"), events=(first, second))
        right = compute_profile_snapshot(user_id=1001, as_of=at("2025-02-01T00:00:00"), events=(second, first))
        self.assertEqual(left, right)
        self.assertEqual(2, left.event_count)
        self.assertGreater(left.interests[0].raw_signal, 0)
        self.assertGreaterEqual(left.profile_confidence, 0)
        self.assertLessEqual(left.profile_confidence, 1)

    def test_profile_snapshot_content_hash_is_replay_stable(self) -> None:
        events = (
            BehaviorForReplay(
                event_id=2,
                event_uuid="hash-event-2",
                event_type="FAVORITE_RESOURCE",
                resource_id=11,
                occurred_at=at("2025-01-02T00:00:00"),
                reason_code=None,
                tags=(ResourceTagEvidence(8, 0.9, 0.8),),
            ),
            BehaviorForReplay(
                event_id=1,
                event_uuid="hash-event-1",
                event_type="VIEW_RESOURCE",
                resource_id=10,
                occurred_at=at("2025-01-01T00:00:00"),
                reason_code=None,
                tags=(ResourceTagEvidence(7, 1.0, 1.0),),
            ),
        )
        evaluation_at = at("2025-02-01T00:00:00")
        first = compute_profile_snapshot(user_id=1001, as_of=evaluation_at, events=events)
        second = compute_profile_snapshot(user_id=1001, as_of=evaluation_at, events=tuple(reversed(events)))
        self.assertEqual(first.input_hash, second.input_hash)
        self.assertEqual(64, len(first.input_hash))
        self.assertEqual(first.event_count, second.event_count)

    def test_already_read_preserves_topic_interest_without_creating_topic_negative(self) -> None:
        snapshot = compute_profile_snapshot(
            user_id=1001,
            as_of=at("2025-02-01T00:00:00"),
            events=(
                BehaviorForReplay(
                    event_id=1,
                    event_uuid="already-read-1",
                    event_type="VIEW_RESOURCE",
                    resource_id=10,
                    occurred_at=at("2025-01-01T00:00:00"),
                    reason_code="ALREADY_READ",
                    tags=(ResourceTagEvidence(7, 1.0, 1.0),),
                ),
            ),
        )
        self.assertEqual((7,), tuple(item.tag_id for item in snapshot.interests))
        self.assertEqual((), snapshot.negatives)


if __name__ == "__main__":
    unittest.main()
