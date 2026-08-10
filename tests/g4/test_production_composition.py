from __future__ import annotations

import unittest

from backend.app.composition import build_production_http_app
from backend.app.config import AppSettings
from backend.app.observability.domain import ComponentReadiness, ComponentStatus


SECRET = "production-composition-test-secret-0123456789"


class UpProbe:
    async def check(self) -> ComponentReadiness:
        return ComponentReadiness(ComponentStatus.UP, required=True)


def settings(**overrides: object) -> AppSettings:
    values: dict[str, object] = {
        "app_env": "production",
        "mysql_password": "isolated-test-password",
        "auth_enabled": True,
        "auth_jwt_secret": SECRET,
        "production_http_enabled": True,
    }
    values.update(overrides)
    return AppSettings(**values)


class ProductionCompositionTest(unittest.TestCase):
    def test_complete_graph_is_explicit_and_does_not_open_connections(self) -> None:
        app = build_production_http_app(
            settings(),
            recommendation_service=object(),
            feedback_service=object(),
            behavior_service=object(),
            readiness_probe=UpProbe(),
            config_bundle_probe=UpProbe(),
        )
        paths = set(app.openapi()["paths"])
        self.assertIn("/api/v1/recommendation-tasks", paths)
        self.assertIn("/api/v1/recommendation-impressions/batch", paths)
        self.assertIn("/api/v1/behavior-events", paths)
        self.assertIn("/api/v1/health/live", paths)

    def test_production_graph_requires_the_explicit_enable_flag(self) -> None:
        with self.assertRaisesRegex(ValueError, "disabled by configuration"):
            build_production_http_app(
                settings(production_http_enabled=False),
                recommendation_service=object(),
                feedback_service=object(),
                behavior_service=object(),
            )

    def test_production_graph_requires_formal_authentication(self) -> None:
        with self.assertRaisesRegex(ValueError, "formal bearer"):
            build_production_http_app(
                settings(auth_enabled=False, auth_jwt_secret=None),
                recommendation_service=object(),
                feedback_service=object(),
                behavior_service=object(),
            )

    def test_production_graph_requires_complete_feedback_loop(self) -> None:
        with self.assertRaisesRegex(ValueError, "feedback and behavior"):
            build_production_http_app(
                settings(),
                recommendation_service=object(),
                feedback_service=object(),
                behavior_service=None,
            )

    def test_non_production_cannot_call_production_graph(self) -> None:
        with self.assertRaisesRegex(ValueError, "RECPRO_APP_ENV=production"):
            build_production_http_app(
                settings(app_env="demo"),
                recommendation_service=object(),
                feedback_service=object(),
                behavior_service=object(),
            )


if __name__ == "__main__":
    unittest.main()
