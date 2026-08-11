from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from backend.app.composition import build_demo_http_app, build_demo_mysql_http_app
from backend.app.config import AppSettings
from backend.app.main import create_app
from backend.app.observability.domain import ComponentReadiness, ComponentStatus


class Probe:
    def __init__(self, status: ComponentStatus = ComponentStatus.UP) -> None:
        self.result = ComponentReadiness(status, required=True)
        self.calls = 0

    async def check(self) -> ComponentReadiness:
        self.calls += 1
        return self.result


def settings(*, app_env: str = "demo") -> AppSettings:
    return AppSettings(
        app_env=app_env,
        mysql_password="isolated-test-password",
    )


class OptInHttpCompositionTests(unittest.TestCase):
    def test_demo_root_exposes_api_and_truthful_optin_readiness(self) -> None:
        mysql_probe = Probe()
        bundle_probe = Probe()
        app = build_demo_http_app(
            settings(),
            recommendation_service=object(),
            readiness_probe=mysql_probe,
            config_bundle_probe=bundle_probe,
        )

        self.assertEqual(0, mysql_probe.calls)
        self.assertEqual(0, bundle_probe.calls)
        self.assertIn("/api/v1/recommendation-tasks", app.openapi()["paths"])

        with TestClient(app) as client:
            response = client.get("/api/v1/health/ready")

        self.assertEqual(200, response.status_code)
        body = response.json()
        self.assertEqual("DEGRADED", body["status"])
        self.assertTrue(body["can_recommend"])
        self.assertEqual("UP", body["components"]["recommendation_pipeline"]["status"])
        self.assertTrue(body["components"]["recommendation_pipeline"]["required"])
        self.assertEqual(
            "recommendation-g3-mysql-v1",
            body["components"]["recommendation_pipeline"]["active_version"],
        )
        self.assertEqual(1, mysql_probe.calls)
        self.assertEqual(1, bundle_probe.calls)

    def test_mysql_demo_root_keeps_service_connection_lazy(self) -> None:
        mysql_probe = Probe()
        bundle_probe = Probe()
        app = build_demo_mysql_http_app(
            settings(),
            readiness_probe=mysql_probe,
            config_bundle_probe=bundle_probe,
        )

        self.assertEqual(0, mysql_probe.calls)
        self.assertEqual(0, bundle_probe.calls)
        self.assertIn("/api/v1/recommendation-tasks", app.openapi()["paths"])

    def test_default_app_remains_health_only_and_cannot_claim_readiness(self) -> None:
        mysql_probe = Probe()
        bundle_probe = Probe()
        app = create_app(
            settings=settings(),
            readiness_probe=mysql_probe,
            config_bundle_probe=bundle_probe,
        )

        self.assertNotIn("/api/v1/recommendation-tasks", app.openapi()["paths"])
        with TestClient(app) as client:
            response = client.get("/api/v1/health/ready")

        self.assertEqual(200, response.status_code)
        self.assertFalse(response.json()["can_recommend"])
        self.assertEqual(
            "DISABLED",
            response.json()["components"]["recommendation_pipeline"]["status"],
        )

    def test_optin_graph_fails_closed_when_mysql_is_unavailable(self) -> None:
        app = build_demo_http_app(
            settings(),
            recommendation_service=object(),
            readiness_probe=Probe(ComponentStatus.DOWN),
            config_bundle_probe=Probe(),
        )

        with TestClient(app) as client:
            response = client.get("/api/v1/health/ready")

        self.assertEqual(503, response.status_code)
        self.assertEqual("CORE_STORAGE_UNAVAILABLE", response.json()["error"]["code"])

    def test_optin_guards_require_service_and_matching_environment(self) -> None:
        with self.assertRaisesRegex(ValueError, "explicit service"):
            create_app(
                settings=settings(),
                recommendation_readiness_enabled=True,
            )

        with self.assertRaisesRegex(ValueError, "RECPRO_APP_ENV=demo"):
            build_demo_http_app(
                settings(app_env="test"),
                recommendation_service=object(),
            )

        with self.assertRaisesRegex(ValueError, "recommendation service"):
            build_demo_http_app(settings(), recommendation_service=None)


if __name__ == "__main__":
    unittest.main()
