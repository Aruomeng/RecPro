from __future__ import annotations

import hashlib
import os
import unittest
from unittest.mock import patch

from backend.app.config import (
    CONFIG_BUNDLE_SCHEMA_PATH,
    CONFIG_BUNDLE_SCHEMA_SHA256,
    DEFAULT_PROMPT_BUNDLE_SHA256,
    PROJECT_ROOT,
    AppSettings,
    load_configuration,
)
from backend.app.shared_kernel.contracts.errors import ErrorCode


class ConfigurationTest(unittest.TestCase):
    def test_frozen_schema_hash_matches_the_runtime_guard(self) -> None:
        self.assertEqual(
            CONFIG_BUNDLE_SCHEMA_SHA256,
            hashlib.sha256(CONFIG_BUNDLE_SCHEMA_PATH.read_bytes()).hexdigest(),
        )

    def test_prompt_bundle_hash_is_frozen_in_runtime_configuration(self) -> None:
        self.assertEqual(
            DEFAULT_PROMPT_BUNDLE_SHA256,
            hashlib.sha256(
                (PROJECT_ROOT / "contracts/prompts/rec-prompts-v1.0.1.json").read_bytes()
            ).hexdigest(),
        )

    def test_valid_environment_loads_without_external_api_key(self) -> None:
        environment = {
            "RECPRO_MYSQL_PASSWORD": "isolated-test-password",
            "RECPRO_APP_ENV": "test",
            "RECPRO_MYSQL_PORT": "3307",
        }
        with patch.dict(os.environ, environment, clear=True):
            state = load_configuration()

        self.assertTrue(state.is_valid)
        self.assertEqual("test", state.settings.app_env)
        self.assertEqual(3307, state.settings.mysql_port)
        self.assertEqual("mock", state.settings.llm_provider)
        self.assertFalse(state.settings.recommendation_pipeline_enabled)
        self.assertEqual(
            PROJECT_ROOT / "contracts/config/examples/rec-1.0.0.json",
            state.settings.config_bundle_path,
        )

    def test_missing_password_fails_closed(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            state = load_configuration()

        self.assertFalse(state.is_valid)
        self.assertEqual(ErrorCode.CONFIG_BUNDLE_INVALID.value, state.error_code)

    def test_invalid_port_fails_closed_without_exposing_input(self) -> None:
        environment = {
            "RECPRO_MYSQL_PASSWORD": "isolated-test-password",
            "RECPRO_MYSQL_PORT": "not-a-port",
        }
        with patch.dict(os.environ, environment, clear=True):
            state = load_configuration()

        self.assertFalse(state.is_valid)
        self.assertEqual(ErrorCode.CONFIG_BUNDLE_INVALID.value, state.error_code)

    def test_short_or_unsafe_password_fails_closed(self) -> None:
        for password in ("short", "contains space but is long"):
            with self.subTest(password=password), patch.dict(
                os.environ,
                {"RECPRO_MYSQL_PASSWORD": password},
                clear=True,
            ):
                state = load_configuration()

            self.assertFalse(state.is_valid)
            self.assertEqual(ErrorCode.CONFIG_BUNDLE_INVALID.value, state.error_code)

    def test_pipeline_cannot_be_enabled_in_g1(self) -> None:
        with self.assertRaises(ValueError):
            AppSettings(
                mysql_password="isolated-test-password",
                recommendation_pipeline_enabled=True,
            )

    def test_worker_is_disabled_by_default_and_requires_a_matching_mode(self) -> None:
        settings = AppSettings(mysql_password="isolated-test-password", app_env="test")
        self.assertFalse(settings.worker_enabled)
        self.assertEqual("disabled", settings.worker_mode)

        with self.assertRaises(ValueError):
            AppSettings(
                mysql_password="isolated-test-password",
                app_env="test",
                worker_enabled=True,
            )
        with self.assertRaises(ValueError):
            AppSettings(
                mysql_password="isolated-test-password",
                app_env="test",
                worker_mode="profile_outbox",
            )

    def test_worker_configuration_accepts_explicit_non_production_profile_mode(self) -> None:
        settings = AppSettings(
            mysql_password="isolated-test-password",
            app_env="test",
            worker_enabled=True,
            worker_mode="profile_outbox",
            worker_id="test-profile-worker",
            worker_batch_limit=4,
            worker_lease_seconds=90,
            worker_max_attempts=4,
        )
        self.assertTrue(settings.worker_enabled)
        self.assertEqual("profile_outbox", settings.worker_mode)
        self.assertEqual(4, settings.worker_batch_limit)

    def test_worker_configuration_rejects_production_write_mode(self) -> None:
        with self.assertRaises(ValueError):
            AppSettings(
                mysql_password="isolated-test-password",
                app_env="production",
                worker_enabled=True,
                worker_mode="profile_outbox",
            )

    def test_deepseek_is_opt_in_and_requires_a_local_key(self) -> None:
        with self.assertRaises(ValueError):
            AppSettings(
                mysql_password="isolated-test-password",
                llm_provider="deepseek",
            )

        settings = AppSettings(
            mysql_password="isolated-test-password",
            llm_provider="deepseek",
            llm_api_key="local-test-deepseek-key-001",
        )
        self.assertEqual("deepseek", settings.llm_provider)
        self.assertEqual("deepseek-v4-flash", settings.llm_model)
        self.assertIsNotNone(settings.llm_api_key)

    def test_g4_llm_intent_requires_demo_http_and_deepseek(self) -> None:
        common = {
            "mysql_password": "isolated-test-password",
            "g4_llm_intent_enabled": True,
        }
        with self.assertRaises(ValueError):
            AppSettings(**common)
        with self.assertRaises(ValueError):
            AppSettings(**common, app_env="demo", g4_http_enabled=True)

        settings = AppSettings(
            **common,
            app_env="demo",
            g4_http_enabled=True,
            llm_provider="deepseek",
            llm_api_key="local-test-deepseek-key-001",
        )
        self.assertTrue(settings.g4_llm_intent_enabled)

    def test_g4_llm_explanation_has_an_independent_fail_closed_gate(self) -> None:
        common = {
            "mysql_password": "isolated-test-password",
            "g4_llm_explanation_enabled": True,
        }
        with self.assertRaises(ValueError):
            AppSettings(**common)
        with self.assertRaises(ValueError):
            AppSettings(**common, app_env="demo", g4_http_enabled=True)

        settings = AppSettings(
            **common,
            app_env="demo",
            g4_http_enabled=True,
            llm_provider="deepseek",
            llm_api_key="local-test-deepseek-key-001",
        )
        self.assertTrue(settings.g4_llm_explanation_enabled)

    def test_external_llm_origin_must_be_https(self) -> None:
        with self.assertRaises(ValueError):
            AppSettings(
                mysql_password="isolated-test-password",
                llm_base_url="http://127.0.0.1:9000",
            )

    def test_bundle_path_is_independent_of_process_working_directory(self) -> None:
        with patch("os.getcwd", return_value="/unrelated-working-directory"):
            settings = AppSettings(
                mysql_password="isolated-test-password",
                config_bundle_path="contracts/config/examples/rec-1.0.0.json",
            )

        self.assertEqual(
            PROJECT_ROOT / "contracts/config/examples/rec-1.0.0.json",
            settings.config_bundle_path,
        )

    def test_absolute_and_parent_traversal_bundle_paths_fail_closed(self) -> None:
        unsafe_paths = (
            "/outside/config.json",
            "../outside/config.json",
            "contracts/../config.json",
        )
        for path in unsafe_paths:
            with self.subTest(path=path), self.assertRaises(ValueError):
                AppSettings(
                    mysql_password="isolated-test-password",
                    config_bundle_path=path,
                )

        for path in ("/outside/prompts.json", "../outside/prompts.json"):
            with self.subTest(prompt_path=path), self.assertRaises(ValueError):
                AppSettings(
                    mysql_password="isolated-test-password",
                    prompt_bundle_path=path,
                )

    def test_path_resolution_os_error_preserves_fail_closed_liveness_state(self) -> None:
        with patch.dict(
            os.environ,
            {"RECPRO_MYSQL_PASSWORD": "isolated-test-password"},
            clear=True,
        ), patch(
            "backend.app.config.Path.resolve",
            side_effect=OSError("synthetic path failure"),
        ):
            state = load_configuration()

        self.assertFalse(state.is_valid)
        self.assertEqual(ErrorCode.CONFIG_BUNDLE_INVALID.value, state.error_code)
