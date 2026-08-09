from __future__ import annotations

import unittest
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app.config import AppSettings
from backend.app.main import create_app
from backend.app.observability.domain import ComponentReadiness, ComponentStatus
from backend.app.recommendation.application.public import (
    RecommendationTaskCommand,
    RecommendationTaskResult,
)


class UpProbe:
    async def check(self) -> ComponentReadiness:
        return ComponentReadiness(ComponentStatus.UP, required=True)


class FakeRecommendationService:
    def __init__(self) -> None:
        self.calls: list[RecommendationTaskCommand] = []

    async def create_task(
        self,
        command: RecommendationTaskCommand,
        *,
        idempotency_key: str,
    ) -> RecommendationTaskResult:
        self.calls.append(command)
        return RecommendationTaskResult(
            status_code=201 if len(self.calls) == 1 else 200,
            replayed=len(self.calls) > 1,
            payload={
                "task_id": str(command.request_id),
                "record_id": 1,
                "trace_id": str(uuid4()),
                "status": "COMPLETED",
                "context_version": 1,
                "evaluation_at": "2026-08-09T00:00:00Z",
                "decision": {
                    "output_type": "TOPIC_RESOURCES",
                    "delivery_strategy": "DIRECT",
                    "explanation_level": "EVIDENCE",
                    "adaptation_state": "NORMAL",
                    "decision_reason_codes": ["SUFFICIENT_RESOURCE_COVERAGE"],
                    "decision_reason": "fixture",
                    "policy_version": "policy-g3-v1",
                },
                "items": [
                    {
                        "item_id": 1,
                        "resource": {
                            "resource_id": 1,
                            "resource_type": "BOOK",
                            "title": "Synthetic resource",
                            "authors": ["Synthetic author"],
                            "publication_year": 2026,
                            "availability_status": "AVAILABLE_BORROW",
                        },
                        "rank_no": 1,
                        "reason_summary": "Evidence-backed fixture.",
                        "evidence_confidence": 0.9,
                    }
                ],
                "warnings": [],
                "versions": {
                    "config_bundle": "rec-1.0.0",
                    "policy": "policy-g3-v1",
                    "ranking": "ranking-g3-v1",
                    "behavior_formula": "profile-g2-v1",
                    "dataset": "synthetic-demo-2026-08",
                },
            },
        )

    async def get_task(self, task_id, *, user_id: int) -> dict[str, object]:
        return {
            "task_id": str(task_id),
            "trace_id": str(uuid4()),
            "status": "COMPLETED",
            "context_version": 1,
            "record_id": 1,
            "evaluation_at": "2026-08-09T00:00:00Z",
            "started_at": "2026-08-09T00:00:00Z",
            "finished_at": "2026-08-09T00:00:01Z",
            "error_code": None,
            "warnings": [],
            "versions": {
                "config_bundle": "rec-1.0.0",
                "policy": "policy-g3-v1",
                "ranking": "ranking-g3-v1",
                "behavior_formula": "profile-g2-v1",
                "dataset": "synthetic-demo-2026-08",
            },
        }

    async def get_trace(self, task_id, *, user_id: int) -> dict[str, object]:
        return {
            "task_id": str(task_id),
            "schema_version": "g3-trace-v1",
            "payload": {"steps": []},
        }


def app_for(service: object, *, enabled: bool = True):
    settings = AppSettings(
        app_env="demo",
        mysql_password="isolated-test-password",
    )
    return create_app(
        settings=settings,
        readiness_probe=UpProbe(),
        config_bundle_probe=UpProbe(),
        recommendation_service=service,
        recommendation_api_enabled=enabled,
    )


class RecommendationAPITest(unittest.TestCase):
    def test_create_and_replay_are_explicit_and_user_scoped(self) -> None:
        service = FakeRecommendationService()
        request_id = uuid4()
        body = {
            "request_id": str(request_id),
            "session_id": str(uuid4()),
            "scene": "SEARCH_AFTER",
            "input_text": "多智能体推荐系统",
            "limit": 5,
        }
        headers = {
            "Idempotency-Key": str(request_id),
            "X-Demo-User-Id": "7",
        }
        with TestClient(app_for(service)) as client:
            first = client.post("/api/v1/recommendation-tasks", json=body, headers=headers)
            second = client.post("/api/v1/recommendation-tasks", json=body, headers=headers)
            task = client.get(
                f"/api/v1/recommendation-tasks/{first.json()['task_id']}",
                headers={"X-Demo-User-Id": "7"},
            )

        self.assertEqual(201, first.status_code)
        self.assertEqual("false", first.headers["Idempotency-Replayed"])
        self.assertEqual(200, second.status_code)
        self.assertEqual("true", second.headers["Idempotency-Replayed"])
        self.assertEqual(7, service.calls[0].user_id)
        self.assertEqual(("BOOK", "PAPER"), service.calls[0].resource_types)
        self.assertEqual(str(request_id), first.json()["task_id"])
        self.assertIn("X-Trace-Id", first.headers)
        self.assertEqual(200, task.status_code)
        self.assertEqual("COMPLETED", task.json()["status"])

    def test_request_id_mismatch_is_rejected_before_service(self) -> None:
        service = FakeRecommendationService()
        request_id = uuid4()
        body = {
            "request_id": str(request_id),
            "session_id": str(uuid4()),
            "scene": "SEARCH_AFTER",
            "input_text": "topic",
        }
        with TestClient(app_for(service)) as client:
            response = client.post(
                "/api/v1/recommendation-tasks",
                json=body,
                headers={
                    "Idempotency-Key": str(uuid4()),
                    "X-Demo-User-Id": "7",
                },
            )

        self.assertEqual(409, response.status_code)
        self.assertEqual("REQUEST_ID_MISMATCH", response.json()["error"]["code"])
        self.assertEqual([], service.calls)

    def test_pipeline_flag_fails_closed(self) -> None:
        service = FakeRecommendationService()
        request_id = uuid4()
        body = {
            "request_id": str(request_id),
            "session_id": str(uuid4()),
            "scene": "SEARCH_AFTER",
            "input_text": "topic",
        }
        with TestClient(app_for(service, enabled=False)) as client:
            response = client.post(
                "/api/v1/recommendation-tasks",
                json=body,
                headers={
                    "Idempotency-Key": str(request_id),
                    "X-Demo-User-Id": "7",
                },
            )

        self.assertEqual(503, response.status_code)
        self.assertEqual("CORE_STORAGE_UNAVAILABLE", response.json()["error"]["code"])
        self.assertEqual([], service.calls)

    def test_opt_in_post_cors_is_explicit(self) -> None:
        service = FakeRecommendationService()
        with TestClient(app_for(service)) as client:
            response = client.options(
                "/api/v1/recommendation-tasks",
                headers={
                    "Origin": "http://localhost:5173",
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "Idempotency-Key, X-Demo-User-Id",
                },
            )

        self.assertEqual(200, response.status_code)
        self.assertIn("POST", response.headers.get("access-control-allow-methods", ""))

    def test_scene_and_output_limits_are_validated(self) -> None:
        service = FakeRecommendationService()
        request_id = uuid4()
        body = {
            "request_id": str(request_id),
            "session_id": str(uuid4()),
            "scene": "SEARCH_AFTER",
            "input_text": "",
            "requested_output_type": "READING_PATH",
            "limit": 5,
        }
        with TestClient(app_for(service)) as client:
            response = client.post(
                "/api/v1/recommendation-tasks",
                json=body,
                headers={
                    "Idempotency-Key": str(request_id),
                    "X-Demo-User-Id": "7",
                },
            )

        self.assertEqual(422, response.status_code)
        self.assertEqual("INVALID_SCENE_SOURCE", response.json()["error"]["code"])
        self.assertEqual([], service.calls)


if __name__ == "__main__":
    unittest.main()
