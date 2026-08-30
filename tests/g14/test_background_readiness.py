from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from backend.app.config import AppSettings
from backend.app.main import create_app
from backend.app.observability.domain import ComponentReadiness, ComponentStatus


class _MysqlProbe:
    async def check(self) -> ComponentReadiness:
        return ComponentReadiness(ComponentStatus.UP, required=True)


class BackgroundReadinessTests(unittest.TestCase):
    def _settings(self) -> AppSettings:
        return AppSettings(app_env="test", mysql_password="isolated-test-password")

    def test_background_planning_is_explicitly_disabled_by_default(self) -> None:
        with TestClient(
            create_app(settings=self._settings(), readiness_probe=_MysqlProbe())
        ) as client:
            component = client.get("/api/v1/health/ready").json()["components"][
                "background_planning"
            ]
        self.assertEqual("DISABLED", component["status"])
        self.assertEqual("BACKGROUND_PLANNING_DISABLED", component["error_code"])

    def test_fixture_planning_can_be_reported_without_model_requests(self) -> None:
        with TestClient(
            create_app(
                settings=self._settings(),
                readiness_probe=_MysqlProbe(),
                background_planning_enabled=True,
                background_planning_version="background-planning-fixture-v1",
                background_planning_provider="FixtureBackgroundPlanner",
            )
        ) as client:
            component = client.get("/api/v1/health/ready").json()["components"][
                "background_planning"
            ]
        self.assertEqual("UP", component["status"])
        self.assertEqual("background-planning-fixture-v1", component["active_version"])
        self.assertEqual("FixtureBackgroundPlanner", component["provider"])


if __name__ == "__main__":
    unittest.main()
