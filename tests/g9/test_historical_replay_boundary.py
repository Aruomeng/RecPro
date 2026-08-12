from __future__ import annotations

import unittest
from datetime import UTC, datetime

from backend.app.evaluation.domain.historical_replay import (
    HistoricalBehaviorFact,
    HistoricalPopularityFact,
    HistoricalResourceFact,
    HistoricalStateFact,
    build_historical_replay_snapshot,
)


def at(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


class HistoricalReplayBoundaryTests(unittest.TestCase):
    def test_future_resource_behavior_state_and_hotness_do_not_change_snapshot(self) -> None:
        evaluation_at = at("2026-01-10T00:00:00")
        resources = (
            HistoricalResourceFact(1, at("2026-01-01T00:00:00"), "book-v1"),
            HistoricalResourceFact(2, at("2026-01-02T00:00:00"), "book-v1"),
        )
        behaviors = (
            HistoricalBehaviorFact(1, at("2026-01-03T00:00:00"), "VIEW_RESOURCE", 1),
        )
        states = (
            HistoricalStateFact(1, "AVAILABLE", at("2026-01-04T00:00:00"), 1),
        )
        popularity = (
            HistoricalPopularityFact(1, at("2026-01-05T00:00:00"), 0.4),
        )
        baseline = build_historical_replay_snapshot(
            evaluation_at=evaluation_at,
            resources=resources,
            behaviors=behaviors,
            states=states,
            popularity=popularity,
        )
        enriched = build_historical_replay_snapshot(
            evaluation_at=evaluation_at,
            resources=(*resources, HistoricalResourceFact(3, at("2026-02-01T00:00:00"), "book-v2")),
            behaviors=(*behaviors, HistoricalBehaviorFact(2, at("2026-01-11T00:00:00"), "BORROW_BOOK", 2)),
            states=(*states, HistoricalStateFact(1, "HIDDEN", at("2026-01-11T00:00:00"), 2)),
            popularity=(*popularity, HistoricalPopularityFact(1, at("2026-01-11T00:00:00"), 1.0)),
        )

        self.assertEqual(baseline, enriched)
        self.assertEqual(2, len(enriched.resources))
        self.assertEqual(1, len(enriched.behaviors))
        self.assertEqual(1, len(enriched.states))
        self.assertEqual(1, len(enriched.popularity))

    def test_snapshot_hash_is_order_independent_for_frozen_facts(self) -> None:
        evaluation_at = at("2026-01-10T00:00:00")
        resources = (
            HistoricalResourceFact(2, at("2026-01-02T00:00:00"), "v1"),
            HistoricalResourceFact(1, at("2026-01-01T00:00:00"), "v1"),
        )
        kwargs = {
            "evaluation_at": evaluation_at,
            "resources": resources,
            "behaviors": (HistoricalBehaviorFact(2, at("2026-01-02T00:00:00"), "VIEW_RESOURCE", 2),),
            "states": (HistoricalStateFact(2, "AVAILABLE", at("2026-01-02T00:00:00"), 1),),
            "popularity": (HistoricalPopularityFact(2, at("2026-01-02T00:00:00"), 0.2),),
        }
        first = build_historical_replay_snapshot(**kwargs)
        second = build_historical_replay_snapshot(**{**kwargs, "resources": tuple(reversed(resources))})
        self.assertEqual(first.content_hash, second.content_hash)


if __name__ == "__main__":
    unittest.main()
