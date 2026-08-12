from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import SecretStr

from backend.app.composition import (
    build_demo_orchestration_service,
    build_research_g4_http_app,
    build_research_g4_recommendation_service,
    build_research_orchestration_service,
)
from backend.app.config import AppSettings
from backend.app.recommendation.adapters.g4_mysql import (
    MySQLG4RecommendationTaskService,
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

    def test_g4_recommendation_root_is_explicit_and_does_not_open_connection(self) -> None:
        opened = False

        async def factory():
            nonlocal opened
            opened = True
            raise AssertionError("composition must not connect during construction")

        service = build_research_g4_recommendation_service(
            settings(app_env="development"), connection_factory=factory
        )
        self.assertIsInstance(service, MySQLG4RecommendationTaskService)
        self.assertFalse(opened)

    def test_g4_recommendation_root_rejects_production(self) -> None:
        with self.assertRaisesRegex(ValueError, "non-production"):
            build_research_g4_recommendation_service(settings(app_env="production"))

    def test_g4_intent_opt_in_does_not_enable_llm_explanation(self) -> None:
        provider = object()
        orchestrator = object()
        with patch(
            "backend.app.composition.build_llm_provider", return_value=provider
        ) as provider_builder, patch(
            "backend.app.composition.build_port_orchestrator",
            return_value=orchestrator,
        ) as orchestrator_builder:
            service = build_research_g4_recommendation_service(
                settings(app_env="demo"),
                connection_factory=lambda: _never(),
                enable_llm_intent_provider=True,
            )
            observed = service._orchestrator_factory(object())

        self.assertIs(orchestrator, observed)
        provider_builder.assert_called_once()
        self.assertIsNone(orchestrator_builder.call_args.kwargs["llm_provider"])
        self.assertIs(
            provider,
            orchestrator_builder.call_args.kwargs["llm_intent_provider"],
        )

    def test_g4_http_root_is_fail_closed_without_explicit_switch(self) -> None:
        with self.assertRaisesRegex(ValueError, "disabled by configuration"):
            build_research_g4_http_app(
                AppSettings(
                    app_env="demo",
                    mysql_password=SecretStr("RecProMysqlRuntime.20260802"),
                ),
                recommendation_service=object(),
            )

    def test_g4_http_root_mounts_only_an_injected_service(self) -> None:
        application = build_research_g4_http_app(
            AppSettings(
                app_env="demo",
                mysql_password=SecretStr("RecProMysqlRuntime.20260802"),
                g4_http_enabled=True,
            ),
            recommendation_service=object(),
        )
        self.assertIn("/api/v1/recommendation-tasks", application.openapi()["paths"])
        self.assertIn("/api/v1/health/ready", application.openapi()["paths"])


async def _never():
    raise AssertionError("connection must not open during construction")


if __name__ == "__main__":
    unittest.main()
