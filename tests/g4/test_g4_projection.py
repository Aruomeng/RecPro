from __future__ import annotations

import asyncio
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from backend.app.api.recommendation import RecommendationExecutionResponse
from backend.app.recommendation.agents.orchestrator import OrchestrationRequest
from backend.app.recommendation.application.g4_projection import (
    G4ProjectionError,
    G4ProjectionVersions,
    G4ResourceProjection,
    build_http_execution_payload,
    build_orchestration_request,
    derive_task_identity,
    split_recall_channels,
)
from backend.app.recommendation.application.orchestration import build_rule_orchestrator
from backend.app.recommendation.domain.public import RecommendationTaskCommand


def command() -> RecommendationTaskCommand:
    return RecommendationTaskCommand(
        request_id=UUID("11111111-1111-1111-1111-111111111111"),
        session_id=UUID("22222222-2222-2222-2222-222222222222"),
        user_id=1001,
        scene="SEARCH_AFTER",
        input_text="多智能体图书馆",
        resource_types=("BOOK",),
        output_type="TOPIC_RESOURCES",
        source_resource_id=None,
        source_item_id=None,
        evaluation_at=None,
        constraints={"source": "test"},
        limit=3,
    )


def orchestration_result():
    now = datetime.now(UTC)
    request = OrchestrationRequest(
        task_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        trace_id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
        session_id=UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"),
        user_id=1001,
        input_text="多智能体推荐",
        resource_types=("BOOK",),
        limit=3,
        evaluation_at=now,
        deadline_at=now + timedelta(minutes=5),
    )
    result = asyncio.run(build_rule_orchestrator().run(request))
    payload = dict(result.payload)
    payload["items"] = [
        {**item, "evidence_confidence": 0.8}
        for item in payload["items"]
    ]
    return replace(result, payload=payload)


class G4ProjectionTests(unittest.TestCase):
    def test_command_maps_to_replay_stable_identity_and_preserves_scene(self) -> None:
        evaluation_at = datetime(2026, 8, 11, 1, 0, tzinfo=UTC)
        deadline_at = evaluation_at + timedelta(minutes=1)
        actual = build_orchestration_request(
            command(), evaluation_at=evaluation_at, deadline_at=deadline_at
        )
        identity = derive_task_identity(command())
        self.assertEqual(identity.task_id, actual.task_id)
        self.assertEqual(identity.trace_id, actual.trace_id)
        self.assertEqual("SEARCH_AFTER", actual.scene)
        self.assertEqual(("BOOK",), actual.resource_types)
        self.assertEqual(evaluation_at, actual.evaluation_at)

    def test_request_mapping_requires_frozen_aware_times(self) -> None:
        evaluation_at = datetime(2026, 8, 11, 1, 0, tzinfo=UTC)
        with self.assertRaisesRegex(G4ProjectionError, "timezone-aware"):
            build_orchestration_request(
                command(),
                evaluation_at=evaluation_at.replace(tzinfo=None),
                deadline_at=evaluation_at + timedelta(minutes=1),
            )
        with self.assertRaisesRegex(G4ProjectionError, "later"):
            build_orchestration_request(
                command(), evaluation_at=evaluation_at, deadline_at=evaluation_at
            )

    def test_split_channels_preserves_components_for_varchar_candidate_rows(self) -> None:
        self.assertEqual(
            ("MYSQL", "GRAPH", "VECTOR"),
            split_recall_channels("MYSQL+GRAPH+VECTOR"),
        )
        with self.assertRaises(G4ProjectionError):
            split_recall_channels("MYSQL+MYSQL")
        with self.assertRaises(G4ProjectionError):
            split_recall_channels("X" * 17)

    def test_complete_result_projects_into_the_frozen_http_contract(self) -> None:
        result = orchestration_result()
        resources = {
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
        payload = build_http_execution_payload(
            result,
            resources=resources,
            versions=G4ProjectionVersions(
                config_bundle="rec-1.0.0", dataset="lib-books-v1"
            ),
            evaluation_at=datetime(2026, 8, 11, 1, 0, tzinfo=UTC),
            record_id=42,
            item_ids={1: 101, 2: 102, 3: 103},
        )
        response = RecommendationExecutionResponse.model_validate(payload)
        self.assertEqual(42, response.record_id)
        self.assertEqual(3, len(response.items or []))
        self.assertEqual(101, response.items[0].item_id)

    def test_projection_fails_closed_when_agent_omits_evidence_confidence(self) -> None:
        result = orchestration_result()
        resources = {
            resource_id: G4ResourceProjection(
                resource_id=resource_id,
                resource_type="BOOK",
                title=f"Book {resource_id}",
                authors=(),
                publication_year=None,
                availability_status="AVAILABLE_ONLINE",
            )
            for resource_id in range(1, 4)
        }
        with self.assertRaisesRegex(G4ProjectionError, "evidence_confidence"):
            build_http_execution_payload(
                replace(
                    result,
                    payload={
                        **result.payload,
                        "items": [
                            {key: value for key, value in item.items() if key != "evidence_confidence"}
                            for item in result.payload["items"]
                        ],
                    },
                ),
                resources=resources,
                versions=G4ProjectionVersions(
                    config_bundle="rec-1.0.0", dataset="lib-books-v1"
                ),
                evaluation_at=datetime(2026, 8, 11, 1, 0, tzinfo=UTC),
                item_ids={1: 101, 2: 102, 3: 103},
            )


if __name__ == "__main__":
    unittest.main()
