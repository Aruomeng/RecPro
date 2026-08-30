from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from backend.app.config import AppSettings
from backend.app.main import create_app
from backend.app.observability.domain import ComponentReadiness, ComponentStatus
from backend.app.shared_kernel.contracts.auth import AuthenticatedPrincipal


class _UpProbe:
    async def check(self) -> ComponentReadiness:
        return ComponentReadiness(ComponentStatus.UP, required=True)


class _MetricsResource:
    def runtime_metrics(self) -> dict[str, object]:
        return {
            "acquire_count": 4,
            "active_leases": 1,
            "average_acquire_ms": 2.5,
            "password": "must-not-cross-boundary",
            "connection_options": {"host": "private"},
        }


def _app(*, debug: bool, resource: object | None = None):
    def resolve(token: str) -> AuthenticatedPrincipal | None:
        if token == "admin":
            return AuthenticatedPrincipal(9001, frozenset({"research_admin"}), token_id=token)
        if token == "user":
            return AuthenticatedPrincipal(9002, frozenset({"user"}), token_id=token)
        return None

    return create_app(
        settings=AppSettings(app_env="production", mysql_password="isolated-test-password"),
        readiness_probe=_UpProbe(),
        config_bundle_probe=_UpProbe(),
        recommendation_service=object(),
        recommendation_api_enabled=True,
        principal_resolver=resolve,
        debug_api_enabled=debug,
        managed_resources=() if resource is None else (resource,),
    )


class RuntimeDiagnosticsAPITest(unittest.TestCase):
    def test_runtime_diagnostics_is_not_mounted_by_default(self) -> None:
        with TestClient(_app(debug=False)) as client:
            response = client.get("/api/v1/debug/runtime")
        self.assertEqual(404, response.status_code)

    def test_runtime_diagnostics_requires_formal_research_admin(self) -> None:
        with TestClient(_app(debug=True, resource=_MetricsResource())) as client:
            no_auth = client.get("/api/v1/debug/runtime")
            demo = client.get(
                "/api/v1/debug/runtime",
                headers={"X-Demo-User-Id": "9001"},
            )
            user = client.get(
                "/api/v1/debug/runtime",
                headers={"Authorization": "Bearer user"},
            )
            admin = client.get(
                "/api/v1/debug/runtime",
                headers={"Authorization": "Bearer admin"},
            )

        self.assertEqual(401, no_auth.status_code)
        self.assertEqual(403, demo.status_code)
        self.assertEqual(403, user.status_code)
        self.assertEqual(200, admin.status_code)

    def test_runtime_diagnostics_redacts_unbounded_resource_metrics(self) -> None:
        with TestClient(_app(debug=True, resource=_MetricsResource())) as client:
            response = client.get(
                "/api/v1/debug/runtime",
                headers={"Authorization": "Bearer admin"},
            )

        payload = response.json()
        self.assertEqual("runtime-diagnostics-v1", payload["schema_version"])
        self.assertFalse(payload["registry_closed"])
        self.assertEqual(1, payload["resource_count"])
        metrics = payload["resources"][0]["metrics"]
        self.assertEqual(4, metrics["acquire_count"])
        self.assertEqual(2.5, metrics["average_acquire_ms"])
        self.assertNotIn("password", metrics)
        self.assertNotIn("connection_options", metrics)


if __name__ == "__main__":
    unittest.main()
