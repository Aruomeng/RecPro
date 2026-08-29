from __future__ import annotations

import importlib
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch


MODULE = "backend.app.g4_demo_main"


class G4DemoEntrypointTests(unittest.TestCase):
    def tearDown(self) -> None:
        sys.modules.pop(MODULE, None)

    def test_entrypoint_is_fail_closed_without_demo_switch(self) -> None:
        with patch.dict(
            os.environ,
            {
                "RECPRO_APP_ENV": "demo",
                "RECPRO_G4_HTTP_ENABLED": "false",
            },
            clear=False,
        ):
            with self.assertRaisesRegex(RuntimeError, "RECPRO_G4_HTTP_ENABLED"):
                importlib.import_module(MODULE)

    def test_entrypoint_requires_demo_environment(self) -> None:
        with patch.dict(
            os.environ,
            {
                "RECPRO_APP_ENV": "development",
                "RECPRO_G4_HTTP_ENABLED": "true",
            },
            clear=False,
        ):
            with self.assertRaisesRegex(RuntimeError, "RECPRO_APP_ENV=demo"):
                importlib.import_module(MODULE)

    def test_explicit_entrypoint_builds_versioned_runtime_with_intent_llm(self) -> None:
        environment = {
            "RECPRO_APP_ENV": "demo",
            "RECPRO_G4_HTTP_ENABLED": "true",
            "RECPRO_G4_LLM_INTENT_ENABLED": "true",
            "RECPRO_G4_LLM_EXPLANATION_ENABLED": "true",
            "RECPRO_G4_DEADLINE_SECONDS": "120",
            "RECPRO_MYSQL_PASSWORD": "demo-g4-entrypoint-password",
            "RECPRO_MYSQL_HOST": "127.0.0.1",
            "RECPRO_MYSQL_PORT": "62306",
            "RECPRO_MYSQL_DATABASE": "recpro",
            "RECPRO_MYSQL_USER": "recpro_runtime",
            "RECPRO_PERSISTENCE_PROBE_ID": "recpro-g2-tianyuhang-20260809a",
            "RECPRO_CONFIG_BUNDLE_SHA256": "220b0fb30f38fef7ca148c43b1f2751715c7df7ecf7d47e7ddfce7ff2847a5c6",
            "RECPRO_LLM_PROVIDER": "deepseek",
            "RECPRO_LLM_API_KEY": "local-test-deepseek-key-001",
            "RECPRO_LIBRARY_NEO4J_HTTP_HOST_PORT": "62688",
            "RECPRO_NEO4J_READ_USER": "recpro_graph_reader",
            "RECPRO_NEO4J_READ_PASSWORD": "demo-g4-neo4j-password",
            "RECPRO_G4_CHROMA_PATH": "data/chroma",
            "RECPRO_G4_CHROMA_SITE_PACKAGES": ".venv-chroma-g6-20260811/lib/python3.11/site-packages",
        }
        loaded = SimpleNamespace(collection=object())
        runtime = SimpleNamespace()
        application = SimpleNamespace(openapi=lambda: {"paths": {"/api/v1/recommendation-tasks": {}}})
        with patch.dict(os.environ, environment, clear=False):
            with patch(
                "scripts.g4_operator_runtime.load_existing_chroma_collection",
                return_value=loaded,
            ) as loader:
                with patch(
                    "backend.app.catalog.runtime.g4_ports.build_g4_readonly_runtime",
                    return_value=runtime,
                ) as runtime_builder:
                    with patch(
                        "backend.app.composition.build_research_g4_http_app_from_runtime",
                        return_value=application,
                    ) as app_builder:
                        module = importlib.import_module(MODULE)

        self.assertIs(module.app, application)
        loader.assert_called_once()
        runtime_builder.assert_called_once()
        self.assertEqual(
            "lib-books-v1-20260810",
            loader.call_args.kwargs["expected_metadata"]["recpro_graph_version"],
        )
        self.assertEqual(
            "lib-books-v2-20260828",
            runtime_builder.call_args.kwargs["graph_version"],
        )
        app_builder.assert_called_once_with(
            app_builder.call_args.args[0],
            runtime=runtime,
            dataset_version="lib-books-v1-20260810",
            enable_llm_provider=False,
            enable_llm_intent_provider=True,
            enable_llm_explanation_provider=True,
            deadline_seconds=120.0,
        )
        self.assertIn("/api/v1/recommendation-tasks", module.app.openapi()["paths"])


if __name__ == "__main__":
    unittest.main()
