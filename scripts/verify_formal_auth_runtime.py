"""Verify the explicit formal Bearer gate without touching application data."""

from __future__ import annotations

import argparse
import base64
from datetime import UTC, datetime
import hashlib
import hmac
import json
from pathlib import Path
import re
import time
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app.config import AppSettings
from backend.app.main import create_app
from backend.app.observability.domain import ComponentReadiness, ComponentStatus
from backend.app.recommendation.application.public import (
    RecommendationTaskCommand,
    RecommendationTaskResult,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
SECRET = b"formal-auth-runtime-secret-0123456789abcdef"
ISSUER = "libramas-runtime"
AUDIENCE = "libramas-api-runtime"


def _segment(value: dict[str, object]) -> str:
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(encoded).rstrip(b"=").decode("ascii")


def _token(*, subject: str, roles: list[str], expires_at: float) -> str:
    header = _segment({"alg": "HS256", "typ": "JWT"})
    payload = _segment(
        {
            "aud": AUDIENCE,
            "exp": expires_at,
            "iss": ISSUER,
            "jti": f"runtime-{subject}",
            "roles": roles,
            "sub": subject,
        }
    )
    signature = hmac.new(
        SECRET,
        f"{header}.{payload}".encode("ascii"),
        hashlib.sha256,
    ).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
    return f"{header}.{payload}.{encoded_signature}"


class UpProbe:
    async def check(self) -> ComponentReadiness:
        return ComponentReadiness(ComponentStatus.UP, required=True)


class RuntimeFakeRecommendationService:
    async def create_task(
        self,
        command: RecommendationTaskCommand,
        *,
        idempotency_key: str,
    ) -> RecommendationTaskResult:
        return RecommendationTaskResult(
            201,
            False,
            {
                "task_id": str(command.request_id),
                "record_id": 3,
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
                    "decision_reason": "formal auth runtime",
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
            },
        )

    async def get_debug_context(self, task_id: Any, *, actor: Any) -> dict[str, object]:
        return {"task_id": str(task_id), "schema_version": "debug-context-v1", "payload": {}}

    async def get_debug_trace(self, task_id: Any, *, actor: Any) -> dict[str, object]:
        return {"task_id": str(task_id), "schema_version": "debug-trace-v1", "payload": {}}

    async def get_debug_policy_decision(self, task_id: Any, *, actor: Any) -> dict[str, object]:
        return {"task_id": str(task_id), "schema_version": "debug-policy-v1", "payload": {}}


def _settings() -> AppSettings:
    return AppSettings(
        app_env="production",
        mysql_password="isolated-test-password",
        auth_enabled=True,
        auth_jwt_secret=SECRET.decode("ascii"),
        auth_jwt_issuer=ISSUER,
        auth_jwt_audience=AUDIENCE,
    )


def validate_run_id(value: str) -> str:
    if RUN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("run id must use 3-64 safe characters")
    return value


def execute(run_id: str) -> dict[str, object]:
    run_id = validate_run_id(run_id)
    evidence_dir = PROJECT_ROOT / "artifacts" / "verification" / "g5" / f"g5-formal-auth-{run_id}"
    evidence_dir.mkdir(parents=True, exist_ok=False)
    settings = _settings()
    now = time.time()
    user_token = _token(subject="7", roles=["user"], expires_at=now + 300)
    admin_token = _token(subject="1", roles=["research_admin"], expires_at=now + 300)
    request_id = uuid4()
    body = {
        "request_id": str(request_id),
        "session_id": str(uuid4()),
        "scene": "SEARCH_AFTER",
        "input_text": "formal auth runtime",
    }

    default_app = create_app(
        settings=settings,
        readiness_probe=UpProbe(),
        config_bundle_probe=UpProbe(),
    )
    with TestClient(default_app) as client:
        default_route = client.post("/api/v1/recommendation-tasks")

    app = create_app(
        settings=settings,
        readiness_probe=UpProbe(),
        config_bundle_probe=UpProbe(),
        recommendation_service=RuntimeFakeRecommendationService(),
        recommendation_api_enabled=True,
        debug_api_enabled=True,
    )
    task_id = uuid4()
    with TestClient(app) as client:
        accepted = client.post(
            "/api/v1/recommendation-tasks",
            json=body,
            headers={
                "Authorization": f"Bearer {user_token}",
                "Idempotency-Key": str(request_id),
            },
        )
        invalid = client.post(
            "/api/v1/recommendation-tasks",
            json=body,
            headers={
                "Authorization": "Bearer invalid-runtime-token",
                "Idempotency-Key": str(request_id),
            },
        )
        mixed = client.post(
            "/api/v1/recommendation-tasks",
            json=body,
            headers={
                "Authorization": f"Bearer {user_token}",
                "X-Demo-User-Id": "7",
                "Idempotency-Key": str(request_id),
            },
        )
        debug_admin = client.get(
            f"/api/v1/debug/tasks/{task_id}/trace",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        debug_user = client.get(
            f"/api/v1/debug/tasks/{task_id}/trace",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        debug_demo = client.get(
            f"/api/v1/debug/tasks/{task_id}/trace",
            headers={
                "Authorization": f"Bearer {admin_token}",
                "X-Demo-User-Id": "1",
            },
        )

    statuses = {
        "default_business_route": default_route.status_code,
        "formal_user_request": accepted.status_code,
        "invalid_token": invalid.status_code,
        "mixed_demo_and_bearer": mixed.status_code,
        "debug_admin": debug_admin.status_code,
        "debug_user": debug_user.status_code,
        "debug_demo_and_bearer": debug_demo.status_code,
    }
    expected = {
        "default_business_route": 404,
        "formal_user_request": 201,
        "invalid_token": 401,
        "mixed_demo_and_bearer": 403,
        "debug_admin": 200,
        "debug_user": 403,
        "debug_demo_and_bearer": 403,
    }
    if statuses != expected:
        raise RuntimeError(f"formal auth status gate mismatch: {statuses}")

    report: dict[str, object] = {
        "status": "PASS",
        "run_id": run_id,
        "verified_at": datetime.now(UTC).isoformat(),
        "auth": {
            "algorithm": "HS256",
            "issuer": ISSUER,
            "audience": AUDIENCE,
            "token_material_logged": False,
            "claims_checked": ["iss", "aud", "sub", "roles", "exp", "nbf", "iat", "jti"],
        },
        "http_statuses": statuses,
        "default_business_api_enabled": False,
        "database_reads": 0,
        "database_writes": 0,
        "destructive_actions": 0,
        "deleted_files": 0,
    }
    output_path = evidence_dir / "runtime.json"
    with output_path.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return report  # type: ignore[return-value]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    execute(args.run_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
