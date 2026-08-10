from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app.composition import build_formal_auth_resolver
from backend.app.config import AppSettings
from backend.app.main import create_app
from backend.app.observability.domain import ComponentReadiness, ComponentStatus
from backend.app.platform.auth import HMACBearerTokenResolver
from backend.app.recommendation.application.public import (
    RecommendationTaskCommand,
    RecommendationTaskResult,
)


SECRET = b"formal-auth-test-secret-0123456789abcdef"
ISSUER = "libramas-test"
AUDIENCE = "libramas-api-test"
FIXED_NOW = 1_800_000_000.0


def _segment(value: dict[str, object]) -> str:
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(encoded).rstrip(b"=").decode("ascii")


def jwt_token(
    *,
    subject: str = "7",
    roles: list[str] | None = None,
    exp: float = FIXED_NOW + 300,
    **claims: object,
) -> str:
    header = _segment({"alg": "HS256", "typ": "JWT"})
    payload: dict[str, object] = {
        "aud": AUDIENCE,
        "exp": exp,
        "iss": ISSUER,
        "roles": roles or ["user"],
        "sub": subject,
    }
    payload.update(claims)
    body = _segment(payload)
    signature = hmac.new(SECRET, f"{header}.{body}".encode("ascii"), hashlib.sha256).digest()
    return f"{header}.{body}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode('ascii')}"


class UpProbe:
    async def check(self) -> ComponentReadiness:
        return ComponentReadiness(ComponentStatus.UP, required=True)


class FormalAuthFakeService:
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
                    "decision_reason": "formal auth test",
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


class FormalAuthTest(unittest.TestCase):
    def test_valid_user_and_admin_claims_are_projected_without_token_material(self) -> None:
        resolver = HMACBearerTokenResolver(
            secret=SECRET,
            issuer=ISSUER,
            audience=AUDIENCE,
            clock=lambda: FIXED_NOW,
        )

        user = resolver(jwt_token(subject="7", jti="user-v1"))
        admin = resolver(
            jwt_token(subject="1", roles=["research_admin"], jti="admin-v1")
        )

        self.assertIsNotNone(user)
        self.assertEqual(7, user.user_id)
        self.assertEqual(frozenset({"user"}), user.roles)
        self.assertEqual("user-v1", user.token_id)
        self.assertIsNotNone(admin)
        self.assertTrue(admin.has_role("research_admin"))

    def test_strict_claim_and_signature_failures_return_none(self) -> None:
        resolver = HMACBearerTokenResolver(
            secret=SECRET,
            issuer=ISSUER,
            audience=AUDIENCE,
            clock=lambda: FIXED_NOW,
        )
        valid = jwt_token()
        header, body, signature = valid.split(".")
        cases = {
            "tampered_signature": f"{header}.{body}.{signature[:-1]}A",
            "expired": jwt_token(exp=FIXED_NOW - 31),
            "not_before": jwt_token(nbf=FIXED_NOW + 31),
            "wrong_issuer": jwt_token(iss="other-issuer"),
            "wrong_audience": jwt_token(aud="other-audience"),
            "missing_exp": jwt_token_without(),
            "unknown_role": jwt_token(roles=["root"]),
            "non_numeric_subject": jwt_token(subject="user-7"),
        }
        for name, token in cases.items():
            with self.subTest(name=name):
                self.assertIsNone(resolver(token))

    def test_configuration_is_explicit_and_default_builder_is_closed(self) -> None:
        default = AppSettings(mysql_password="isolated-test-password")
        self.assertFalse(default.auth_enabled)
        self.assertIsNone(build_formal_auth_resolver(default))

        with self.assertRaises(ValueError):
            AppSettings(
                mysql_password="isolated-test-password",
                auth_enabled=True,
            )
        with self.assertRaises(ValueError):
            AppSettings(
                mysql_password="isolated-test-password",
                auth_enabled=True,
                auth_jwt_secret="too-short",
            )

    def test_auth_enabled_alone_does_not_expose_default_business_routes(self) -> None:
        settings = AppSettings(
            mysql_password="isolated-test-password",
            app_env="production",
            auth_enabled=True,
            auth_jwt_secret=SECRET.decode("ascii"),
        )
        with TestClient(
            create_app(
                settings=settings,
                readiness_probe=UpProbe(),
                config_bundle_probe=UpProbe(),
            )
        ) as client:
            response = client.post("/api/v1/recommendation-tasks")
        self.assertEqual(404, response.status_code)

    def test_explicit_service_automatically_uses_formal_bearer_resolver(self) -> None:
        settings = AppSettings(
            mysql_password="isolated-test-password",
            app_env="production",
            auth_enabled=True,
            auth_jwt_secret=SECRET.decode("ascii"),
            auth_jwt_issuer=ISSUER,
            auth_jwt_audience=AUDIENCE,
        )
        request_id = uuid4()
        body = {
            "request_id": str(request_id),
            "session_id": str(uuid4()),
            "scene": "SEARCH_AFTER",
            "input_text": "formal token",
        }
        app = create_app(
            settings=settings,
            readiness_probe=UpProbe(),
            config_bundle_probe=UpProbe(),
            recommendation_service=FormalAuthFakeService(),
            recommendation_api_enabled=True,
        )
        with TestClient(app) as client:
            accepted = client.post(
                "/api/v1/recommendation-tasks",
                json=body,
                headers={
                    "Authorization": f"Bearer {jwt_token(subject='7', exp=time.time() + 300)}",
                    "Idempotency-Key": str(request_id),
                },
            )
            rejected = client.post(
                "/api/v1/recommendation-tasks",
                json=body,
                headers={
                    "Authorization": "Bearer not-a-jwt",
                    "Idempotency-Key": str(request_id),
                },
            )
            demo_header = client.post(
                "/api/v1/recommendation-tasks",
                json=body,
                headers={
                    "Authorization": f"Bearer {jwt_token(subject='7', exp=time.time() + 300)}",
                    "X-Demo-User-Id": "7",
                    "Idempotency-Key": str(request_id),
                },
            )
        self.assertEqual(201, accepted.status_code)
        self.assertEqual(401, rejected.status_code)
        self.assertEqual(403, demo_header.status_code)


def jwt_token_without() -> str:
    header = _segment({"alg": "HS256", "typ": "JWT"})
    payload = {
        "aud": AUDIENCE,
        "iss": ISSUER,
        "roles": ["user"],
        "sub": "7",
    }
    body = _segment(payload)
    signature = hmac.new(SECRET, f"{header}.{body}".encode("ascii"), hashlib.sha256).digest()
    return f"{header}.{body}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode('ascii')}"


if __name__ == "__main__":
    unittest.main()
