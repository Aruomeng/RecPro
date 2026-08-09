from __future__ import annotations

import unittest
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from backend.app.config import AppSettings
from backend.app.main import create_app
from backend.app.observability.domain import ComponentReadiness, ComponentStatus
from backend.app.recommendation.application.public import RecommendationTaskCommand, RecommendationTaskResult
from backend.app.shared_kernel.contracts.auth import AuthenticatedPrincipal


class UpProbe:
    async def check(self) -> ComponentReadiness:
        return ComponentReadiness(ComponentStatus.UP, required=True)


def execution_payload(task_id: UUID, *, status: str = "COMPLETED", context_version: int = 1) -> dict[str, object]:
    return {
        "task_id": str(task_id),
        "record_id": 3 if status == "COMPLETED" else None,
        "trace_id": str(uuid4()),
        "status": status,
        "context_version": context_version,
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
        "items": [],
        "warnings": [],
        "versions": {
            "config_bundle": "rec-1.0.0",
            "policy": "policy-g3-v1",
            "ranking": "ranking-g3-v1",
            "behavior_formula": "profile-g2-v1",
            "dataset": "synthetic-demo-2026-08",
        },
    }


class SecureFakeService:
    def __init__(self) -> None:
        self.commands: list[RecommendationTaskCommand] = []

    async def create_task(self, command: RecommendationTaskCommand, *, idempotency_key: str) -> RecommendationTaskResult:
        self.commands.append(command)
        return RecommendationTaskResult(201, False, execution_payload(command.request_id))

    async def get_task(self, task_id: UUID, *, user_id: int) -> dict[str, object]:
        return {
            "task_id": str(task_id),
            "trace_id": str(uuid4()),
            "status": "COMPLETED",
            "context_version": 1,
            "record_id": 3,
            "evaluation_at": "2026-08-09T00:00:00Z",
            "started_at": "2026-08-09T00:00:00Z",
            "finished_at": "2026-08-09T00:00:01Z",
            "error_code": None,
            "warnings": [],
            "versions": execution_payload(task_id)["versions"],
        }

    async def get_trace(self, task_id: UUID, *, user_id: int) -> dict[str, object]:
        return {
            "task_id": str(task_id),
            "schema_version": "g3-trace-v1",
            "payload": {"trace_id": str(uuid4()), "complete": True, "steps": []},
        }

    async def submit_clarification(self, task_id: UUID, **kwargs: object) -> RecommendationTaskResult:
        return RecommendationTaskResult(200, kwargs["idempotency_key"] == "clarify-replay", execution_payload(task_id, context_version=2))

    async def get_debug_context(self, task_id: UUID, *, actor: AuthenticatedPrincipal) -> dict[str, object]:
        return {
            "task_id": str(task_id),
            "schema_version": "debug-context-v1",
            "payload": {"actor_user_id": actor.user_id, "contexts": []},
        }

    async def get_debug_trace(self, task_id: UUID, *, actor: AuthenticatedPrincipal) -> dict[str, object]:
        return {
            "task_id": str(task_id),
            "schema_version": "debug-trace-v1",
            "payload": {"trace_id": str(uuid4()), "complete": True, "steps": []},
        }

    async def get_debug_policy_decision(self, task_id: UUID, *, actor: AuthenticatedPrincipal) -> dict[str, object]:
        return {
            "task_id": str(task_id),
            "schema_version": "debug-policy-v1",
            "payload": {"decisions": []},
        }


def app_for(
    service: SecureFakeService,
    *,
    resolver=None,
    debug: bool = False,
    env: str = "production",
):
    settings = AppSettings(app_env=env, mysql_password="isolated-test-password")
    return create_app(
        settings=settings,
        readiness_probe=UpProbe(),
        config_bundle_probe=UpProbe(),
        recommendation_service=service,
        recommendation_api_enabled=True,
        principal_resolver=resolver,
        debug_api_enabled=debug,
    )


class AuthDebugClarificationAPITest(unittest.TestCase):
    def test_formal_bearer_identity_is_injected_and_demo_header_is_rejected(self) -> None:
        service = SecureFakeService()

        def resolve(token: str) -> AuthenticatedPrincipal | None:
            return AuthenticatedPrincipal(11, frozenset({"user"}), token_id=token)

        request_id = uuid4()
        body = {
            "request_id": str(request_id),
            "session_id": str(uuid4()),
            "scene": "SEARCH_AFTER",
            "input_text": "formal identity",
        }
        with TestClient(app_for(service, resolver=resolve)) as client:
            accepted = client.post(
                "/api/v1/recommendation-tasks",
                json=body,
                headers={"Authorization": "Bearer test-token", "Idempotency-Key": str(request_id)},
            )
            rejected = client.post(
                "/api/v1/recommendation-tasks",
                json=body,
                headers={
                    "Authorization": "Bearer test-token",
                    "X-Demo-User-Id": "11",
                    "Idempotency-Key": str(request_id),
                },
            )
        self.assertEqual(201, accepted.status_code)
        self.assertEqual(11, service.commands[0].user_id)
        self.assertEqual(403, rejected.status_code)
        self.assertEqual("RESOURCE_ACCESS_FORBIDDEN", rejected.json()["error"]["code"])

    def test_formal_route_without_resolver_fails_closed(self) -> None:
        service = SecureFakeService()
        request_id = uuid4()
        body = {
            "request_id": str(request_id),
            "session_id": str(uuid4()),
            "scene": "SEARCH_AFTER",
            "input_text": "no resolver",
        }
        with TestClient(app_for(service)) as client:
            response = client.post(
                "/api/v1/recommendation-tasks",
                json=body,
                headers={"Authorization": "Bearer unknown", "Idempotency-Key": str(request_id)},
            )
        self.assertEqual(401, response.status_code)
        self.assertEqual("AUTHENTICATION_REQUIRED", response.json()["error"]["code"])

    def test_debug_is_opt_in_and_requires_research_admin_bearer(self) -> None:
        service = SecureFakeService()
        task_id = uuid4()

        def resolve(token: str) -> AuthenticatedPrincipal | None:
            roles = {"research_admin"} if token == "admin" else {"user"}
            return AuthenticatedPrincipal(99, frozenset(roles), token_id=token)

        with TestClient(app_for(service, resolver=resolve, debug=False)) as client:
            absent = client.get(f"/api/v1/debug/tasks/{task_id}/trace")
        self.assertEqual(404, absent.status_code)

        with TestClient(app_for(service, resolver=resolve, debug=True)) as client:
            no_auth = client.get(f"/api/v1/debug/tasks/{task_id}/trace")
            user = client.get(
                f"/api/v1/debug/tasks/{task_id}/trace",
                headers={"Authorization": "Bearer user"},
            )
            demo = client.get(
                f"/api/v1/debug/tasks/{task_id}/trace",
                headers={"Authorization": "Bearer admin", "X-Demo-User-Id": "99"},
            )
            admin = client.get(
                f"/api/v1/debug/tasks/{task_id}/trace",
                headers={"Authorization": "Bearer admin"},
            )
        self.assertEqual(401, no_auth.status_code)
        self.assertEqual(403, user.status_code)
        self.assertEqual(403, demo.status_code)
        self.assertEqual(200, admin.status_code)
        self.assertEqual("debug-trace-v1", admin.json()["schema_version"])

    def test_clarification_is_idempotent_and_preserves_task_id(self) -> None:
        service = SecureFakeService()
        task_id = uuid4()
        with TestClient(app_for(service, env="demo")) as client:
            first = client.post(
                f"/api/v1/recommendation-tasks/{task_id}/clarifications",
                json={"context_version": 1, "answers": {"topic": "多智能体", "resource_types": "BOOK_AND_PAPER"}},
                headers={"X-Demo-User-Id": "7", "Idempotency-Key": "clarify-one"},
            )
            replay = client.post(
                f"/api/v1/recommendation-tasks/{task_id}/clarifications",
                json={"context_version": 1, "answers": {"topic": "多智能体", "resource_types": "BOOK_AND_PAPER"}},
                headers={"X-Demo-User-Id": "7", "Idempotency-Key": "clarify-replay"},
            )
        self.assertEqual(200, first.status_code)
        self.assertEqual(str(task_id), first.json()["task_id"])
        self.assertEqual("false", first.headers["Idempotency-Replayed"])
        self.assertEqual(200, replay.status_code)
        self.assertEqual("true", replay.headers["Idempotency-Replayed"])


if __name__ == "__main__":
    unittest.main()
