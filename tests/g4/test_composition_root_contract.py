from __future__ import annotations

import unittest
from types import SimpleNamespace

from pydantic import SecretStr

from backend.app.composition import (
    build_demo_orchestration_service,
    build_research_orchestration_service,
)
from backend.app.recommendation.application.persistent_orchestration import (
    PersistentOrchestrationService,
)


def settings(*, app_env: str):
    return SimpleNamespace(
        app_env=app_env,
        mysql_host="127.0.0.1",
        mysql_port=62306,
        mysql_database="recpro",
        mysql_user="recpro_runtime",
        mysql_password=SecretStr("RecProMysqlRuntime.20260802"),
        mysql_connect_timeout_seconds=3.0,
    )


class CompositionRootContractTests(unittest.TestCase):
    def test_research_root_is_explicit_and_does_not_open_connection(self) -> None:
        opened = False

        async def factory():
            nonlocal opened
            opened = True
            raise AssertionError("composition must not connect during construction")

        service = build_research_orchestration_service(
            settings(app_env="development"), connection_factory=factory
        )
        self.assertIsInstance(service, PersistentOrchestrationService)
        self.assertFalse(opened)

    def test_research_root_rejects_production_by_default(self) -> None:
        with self.assertRaisesRegex(ValueError, "non-production"):
            build_research_orchestration_service(settings(app_env="production"))

    def test_demo_root_requires_demo_environment(self) -> None:
        with self.assertRaisesRegex(ValueError, "RECPRO_APP_ENV=demo"):
            build_demo_orchestration_service(settings(app_env="development"))

        service = build_demo_orchestration_service(
            settings(app_env="demo"), connection_factory=lambda: _never()
        )
        self.assertIsInstance(service, PersistentOrchestrationService)


async def _never():
    raise AssertionError("connection must not open during construction")


if __name__ == "__main__":
    unittest.main()
