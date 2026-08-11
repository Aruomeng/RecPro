from __future__ import annotations

import asyncio
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from backend.app.recommendation.agents.orchestrator import OrchestrationRequest
from backend.app.recommendation.application.g4_persistence import (
    build_g4_projection_write_plan,
)
from backend.app.recommendation.application.g4_projection import (
    G4ProjectionError,
    G4ProjectionVersions,
    G4ResourceProjection,
    derive_task_identity,
)
from backend.app.recommendation.application.orchestration import build_rule_orchestrator
from backend.app.recommendation.domain.public import RecommendationTaskCommand


def base_command(*, resource_types: tuple[str, ...] = ("BOOK",)) -> RecommendationTaskCommand:
    return RecommendationTaskCommand(
        request_id=UUID("11111111-1111-1111-1111-111111111111"),
        session_id=UUID("22222222-2222-2222-2222-222222222222"),
        user_id=1001,
        scene="SEARCH_AFTER",
        input_text="多智能体推荐",
        resource_types=resource_types,
        output_type="TOPIC_RESOURCES",
        source_resource_id=None,
        source_item_id=None,
        evaluation_at=None,
        constraints={},
        limit=3,
    )


def enriched_result():
    now = datetime.now(UTC)
    identity = derive_task_identity(base_command())
    request = OrchestrationRequest(
        task_id=identity.task_id,
        trace_id=identity.trace_id,
        session_id=UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"),
        user_id=1001,
        input_text="多智能体推荐",
        resource_types=("BOOK",),
        limit=3,
        evaluation_at=now,
        deadline_at=now + timedelta(minutes=5),
    )
    result = asyncio.run(build_rule_orchestrator().run(request))
    items = []
    for item in result.payload["items"]:
        score = float(item["score"])
        items.append(
            {
                **item,
                "evidence_confidence": 0.8,
                "channel_scores": {"MYSQL": score},
                "channel_ranks": {"MYSQL": int(item["rank_no"])},
                "primary_channel": "MYSQL",
            }
        )
    return replace(result, payload={**result.payload, "items": items})


def resources() -> dict[int, G4ResourceProjection]:
    return {
        resource_id: G4ResourceProjection(
            resource_id=resource_id,
            resource_type="BOOK",
            title=f"Book {resource_id}",
            authors=("Author",),
            publication_year=2024,
            availability_status="AVAILABLE_BORROW",
        )
        for resource_id in range(1, 4)
    }


class G4PersistencePlanTests(unittest.TestCase):
    def test_completed_plan_contains_task_transitions_channels_and_items(self) -> None:
        result = enriched_result()
        plan = build_g4_projection_write_plan(
            base_command(),
            result,
            resources=resources(),
            versions=G4ProjectionVersions(
                config_bundle="rec-1.0.0", dataset="lib-books-v1"
            ),
            evaluation_at=datetime(2026, 8, 11, 1, 0, tzinfo=UTC),
            started_at=datetime(2026, 8, 11, 1, 0, 1, tzinfo=UTC),
        )
        self.assertEqual("COMPLETED", plan.status)
        self.assertEqual(3, len(plan.items))
        self.assertEqual(3, len(plan.candidates))
        self.assertEqual({"MYSQL"}, {row.channel for row in plan.candidates})
        self.assertEqual(8, len(plan.transitions))
        self.assertEqual(plan.task_id, result.task_id)
        self.assertEqual("TOPIC_RECOMMENDATION", plan.intent_type)

    def test_plan_fails_closed_before_sql_when_channel_details_are_missing(self) -> None:
        result = enriched_result()
        result = replace(
            result,
            payload={
                **result.payload,
                "items": [
                    {
                        key: value
                        for key, value in item.items()
                        if key not in {"channel_scores", "channel_ranks", "primary_channel"}
                    }
                    for item in result.payload["items"]
                ],
            },
        )
        with self.assertRaisesRegex(G4ProjectionError, "channel_scores"):
            build_g4_projection_write_plan(
                base_command(),
                result,
                resources=resources(),
                versions=G4ProjectionVersions(
                    config_bundle="rec-1.0.0", dataset="lib-books-v1"
                ),
                evaluation_at=datetime(2026, 8, 11, 1, 0, tzinfo=UTC),
                started_at=datetime(2026, 8, 11, 1, 0, 1, tzinfo=UTC),
            )

    def test_waiting_plan_has_questions_and_no_business_items(self) -> None:
        now = datetime.now(UTC)
        command = base_command(resource_types=())
        command = replace(command, input_text=None)
        identity = derive_task_identity(command)
        request = OrchestrationRequest(
            task_id=identity.task_id,
            trace_id=identity.trace_id,
            session_id=UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"),
            user_id=1001,
            input_text=None,
            resource_types=(),
            limit=3,
            evaluation_at=now,
            deadline_at=now + timedelta(minutes=5),
        )
        result = asyncio.run(build_rule_orchestrator().run(request))
        plan = build_g4_projection_write_plan(
            command,
            result,
            resources={},
            versions=G4ProjectionVersions(
                config_bundle="rec-1.0.0", dataset="lib-books-v1"
            ),
            evaluation_at=datetime(2026, 8, 11, 1, 0, tzinfo=UTC),
            started_at=datetime(2026, 8, 11, 1, 0, 1, tzinfo=UTC),
        )
        self.assertEqual("WAITING_CLARIFICATION", plan.status)
        self.assertEqual(2, len(plan.questions))
        self.assertEqual((), plan.items)
        self.assertEqual((), plan.candidates)


if __name__ == "__main__":
    unittest.main()
