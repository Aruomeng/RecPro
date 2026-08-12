from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from backend.app.config import AppSettings
from backend.app.feedback.application.public import (
    BehaviorAppendCommand,
    BehaviorReceipt,
    FeedbackCommand,
    FeedbackReceipt,
    ImpressionCommand,
    ImpressionReceipt,
)
from backend.app.main import create_app
from backend.app.observability.domain import ComponentReadiness, ComponentStatus
from backend.app.shared_kernel.contracts.enums import BehaviorEventType


class UpProbe:
    async def check(self) -> ComponentReadiness:
        return ComponentReadiness(ComponentStatus.UP, required=True)


class FakeFeedbackService:
    def __init__(self) -> None:
        self.impressions: list[ImpressionCommand] = []
        self.feedback: list[FeedbackCommand] = []

    async def record_impression(self, command: ImpressionCommand) -> ImpressionReceipt:
        replayed = any(item.impression_uuid == command.impression_uuid for item in self.impressions)
        if not replayed:
            self.impressions.append(command)
        return ImpressionReceipt(command.impression_uuid, 101, 201, True, replayed)

    async def record_feedback(self, command: FeedbackCommand) -> FeedbackReceipt:
        replayed = any(item.feedback_uuid == command.feedback_uuid for item in self.feedback)
        if not replayed:
            self.feedback.append(command)
        return FeedbackReceipt(
            command.feedback_uuid,
            301,
            401,
            501,
            {
                "state_type": "HIDDEN",
                "suppress_until": command.occurred_at + timedelta(days=30),
            },
            replayed,
        )


class FakeBehaviorService:
    def __init__(self) -> None:
        self.commands: list[BehaviorAppendCommand] = []

    async def append(self, command: BehaviorAppendCommand) -> BehaviorReceipt:
        replayed = any(item.event_uuid == command.event_uuid for item in self.commands)
        if not replayed:
            self.commands.append(command)
        return BehaviorReceipt(command.event_uuid, 601, 701, replayed)


def app_for(
    feedback_service: object,
    behavior_service: object,
    *,
    enabled: bool = True,
):
    settings = AppSettings(app_env="demo", mysql_password="isolated-test-password")
    return create_app(
        settings=settings,
        readiness_probe=UpProbe(),
        config_bundle_probe=UpProbe(),
        feedback_service=feedback_service,
        behavior_service=behavior_service,
        feedback_api_enabled=enabled,
    )


class FeedbackAPITest(unittest.TestCase):
    def test_impression_batch_is_user_scoped_and_item_idempotent(self) -> None:
        feedback = FakeFeedbackService()
        behavior = FakeBehaviorService()
        impression_uuid = uuid4()
        body = {
            "impressions": [
                {
                    "impression_uuid": str(impression_uuid),
                    "recommendation_item_id": 7,
                    "position": 1,
                    "rendered_at": "2025-12-30T12:00:00Z",
                    "visible_started_at": "2025-12-30T12:00:00Z",
                    "visible_ms": 1500,
                    "max_visible_ratio": 0.8,
                }
            ]
        }
        headers = {"Idempotency-Key": "batch-one", "X-Demo-User-Id": "7"}
        with TestClient(app_for(feedback, behavior)) as client:
            first = client.post("/api/v1/recommendation-impressions/batch", json=body, headers=headers)
            replay = client.post("/api/v1/recommendation-impressions/batch", json=body, headers=headers)
        self.assertEqual(200, first.status_code)
        self.assertEqual({"accepted_count": 1, "replayed_count": 0, "rejected_count": 0}, {key: first.json()[key] for key in ("accepted_count", "replayed_count", "rejected_count")})
        self.assertEqual(200, replay.status_code)
        self.assertEqual(1, replay.json()["replayed_count"])
        self.assertEqual("true", replay.headers["Idempotency-Replayed"])
        self.assertEqual(7, feedback.impressions[0].user_id)
        self.assertEqual(
            "RETURN_RESULT",
            first.json()["results"][0]["agent_action"]["action"],
        )

    def test_feedback_returns_pending_then_replayed(self) -> None:
        feedback = FakeFeedbackService()
        behavior = FakeBehaviorService()
        feedback_uuid = uuid4()
        body = {
            "feedback_uuid": str(feedback_uuid),
            "impression_uuid": str(uuid4()),
            "feedback_type": "NOT_INTERESTED",
            "reason_code": "TOPIC_NOT_INTERESTED",
        }
        headers = {"Idempotency-Key": str(feedback_uuid), "X-Demo-User-Id": "9"}
        with TestClient(app_for(feedback, behavior)) as client:
            first = client.post("/api/v1/recommendation-items/7/feedback", json=body, headers=headers)
            replay = client.post("/api/v1/recommendation-items/7/feedback", json=body, headers=headers)
        self.assertEqual(202, first.status_code)
        self.assertEqual("ACCEPTED", first.json()["status"])
        self.assertEqual("PENDING", first.json()["profile_update_status"])
        self.assertEqual(200, replay.status_code)
        self.assertEqual("REPLAYED", replay.json()["status"])
        self.assertEqual("true", replay.headers["Idempotency-Replayed"])
        self.assertEqual(9, feedback.feedback[0].user_id)
        self.assertEqual(
            "PROPOSE_PROFILE_DELTA",
            first.json()["agent_action"]["action"],
        )
        self.assertEqual(
            "RETURN_RESULT",
            replay.json()["agent_action"]["action"],
        )

    def test_behavior_accepts_direct_events_and_rejects_derived_events(self) -> None:
        feedback = FakeFeedbackService()
        behavior = FakeBehaviorService()
        event_uuid = uuid4()
        body = {
            "event_uuid": str(event_uuid),
            "session_id": str(uuid4()),
            "event_type": "CLICK_RECOMMENDATION",
            "recommendation_item_id": 7,
            "impression_uuid": str(uuid4()),
            "resource_id": 11,
            "occurred_at": "2025-12-30T12:00:00Z",
        }
        with TestClient(app_for(feedback, behavior)) as client:
            accepted = client.post(
                "/api/v1/behavior-events",
                json=body,
                headers={"Idempotency-Key": str(event_uuid), "X-Demo-User-Id": "7"},
            )
            derived_body = {**body, "event_uuid": str(uuid4()), "event_type": "FAVORITE_RESOURCE"}
            derived_uuid = UUID(derived_body["event_uuid"])
            derived = client.post(
                "/api/v1/behavior-events",
                json=derived_body,
                headers={"Idempotency-Key": str(derived_uuid), "X-Demo-User-Id": "7"},
            )
        self.assertEqual(202, accepted.status_code)
        self.assertEqual("PENDING", accepted.json()["profile_update_status"])
        self.assertEqual(
            "PROPOSE_PROFILE_DELTA",
            accepted.json()["agent_action"]["action"],
        )
        self.assertEqual(BehaviorEventType.CLICK_RECOMMENDATION, behavior.commands[0].event_type)
        self.assertEqual("DERIVED_EVENT_NOT_ALLOWED", derived.json()["error"]["code"])
        self.assertEqual(422, derived.status_code)

    def test_same_behavior_uuid_replay_keeps_one_event_fact(self) -> None:
        feedback = FakeFeedbackService()
        behavior = FakeBehaviorService()
        event_uuid = uuid4()
        body = {
            "event_uuid": str(event_uuid),
            "session_id": str(uuid4()),
            "event_type": "CLICK_RECOMMENDATION",
            "recommendation_item_id": 7,
            "impression_uuid": str(uuid4()),
            "resource_id": 11,
            "occurred_at": "2025-12-30T12:00:00Z",
        }
        headers = {"Idempotency-Key": str(event_uuid), "X-Demo-User-Id": "7"}
        with TestClient(app_for(feedback, behavior)) as client:
            first = client.post("/api/v1/behavior-events", json=body, headers=headers)
            replay = client.post("/api/v1/behavior-events", json=body, headers=headers)
        self.assertEqual(202, first.status_code)
        self.assertEqual(200, replay.status_code)
        self.assertEqual("true", replay.headers["Idempotency-Replayed"])
        self.assertEqual(1, len(behavior.commands))

    def test_auth_and_opt_in_gate_fail_closed(self) -> None:
        feedback = FakeFeedbackService()
        behavior = FakeBehaviorService()
        body = {"impressions": [{
            "impression_uuid": str(uuid4()),
            "recommendation_item_id": 7,
            "position": 1,
            "rendered_at": "2025-12-30T12:00:00Z",
            "visible_ms": 0,
            "max_visible_ratio": 0,
        }]}
        with TestClient(app_for(feedback, behavior, enabled=False)) as client:
            disabled = client.post(
                "/api/v1/recommendation-impressions/batch",
                json=body,
                headers={"Idempotency-Key": "batch-one", "X-Demo-User-Id": "7"},
            )
        with TestClient(app_for(feedback, behavior)) as client:
            unauthenticated = client.post(
                "/api/v1/recommendation-impressions/batch",
                json=body,
                headers={"Idempotency-Key": "batch-one"},
            )
        self.assertEqual(503, disabled.status_code)
        self.assertEqual("CORE_STORAGE_UNAVAILABLE", disabled.json()["error"]["code"])
        self.assertEqual(401, unauthenticated.status_code)
        self.assertEqual("AUTHENTICATION_REQUIRED", unauthenticated.json()["error"]["code"])

    def test_default_app_does_not_expose_interaction_routes(self) -> None:
        with TestClient(create_app(settings=AppSettings(app_env="demo", mysql_password="isolated-test-password"))) as client:
            response = client.post("/api/v1/behavior-events", json={})
        self.assertEqual(404, response.status_code)


if __name__ == "__main__":
    unittest.main()
