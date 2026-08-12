from __future__ import annotations

from pathlib import Path
from unittest.mock import patch
import unittest

from pydantic import SecretStr

from backend.app.config import AppSettings
from backend.app.llm.adapters.deepseek import DeepSeekLLMProvider
from scripts.verify_llm_real_call_readiness import build_report


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class LLMRealCallReadinessTest(unittest.TestCase):
    def test_valid_deepseek_config_is_ready_only_for_explicit_opt_in(self) -> None:
        settings = AppSettings(
            mysql_password="isolated-test-password",
            llm_provider="deepseek",
            llm_api_key="local-test-deepseek-key-001",
        )
        provider = DeepSeekLLMProvider(api_key=SecretStr("local-test-deepseek-key-001"))
        with patch(
            "scripts.verify_llm_real_call_readiness._settings_from_file",
            return_value=settings,
        ), patch(
            "scripts.verify_llm_real_call_readiness.build_llm_provider",
            return_value=provider,
        ):
            report = build_report(env_file=PROJECT_ROOT / "README.md")

        self.assertEqual("READY_FOR_EXPLICIT_OPT_IN", report["status"])
        self.assertTrue(report["provider"]["constructed"])
        self.assertFalse(report["gates"]["external_call_authorized"])
        self.assertEqual(0, report["safety"]["external_llm_requests"])

    def test_mock_config_is_blocked_without_network(self) -> None:
        settings = AppSettings(mysql_password="isolated-test-password")
        with patch(
            "scripts.verify_llm_real_call_readiness._settings_from_file",
            return_value=settings,
        ):
            report = build_report(env_file=PROJECT_ROOT / "README.md")

        self.assertEqual("BLOCKED", report["status"])
        self.assertIn("RECPRO_LLM_PROVIDER is not deepseek", report["blockers"])
        self.assertEqual(0, report["safety"]["network_requests"])


if __name__ == "__main__":
    unittest.main()
