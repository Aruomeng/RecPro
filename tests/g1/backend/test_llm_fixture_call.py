from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch
import unittest

from backend.app.config import AppSettings
from backend.app.llm.ports.public import LLMResult
from scripts import execute_llm_fixture_call as fixture_call


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class LLMFixtureCallTest(unittest.TestCase):
    def test_exact_confirmation_is_required_before_provider_construction(self) -> None:
        with patch.object(fixture_call, "build_llm_provider") as build_provider:
            with self.assertRaises(ValueError):
                asyncio.run(
                    fixture_call.execute(
                        env_file=PROJECT_ROOT / "README.md",
                        run_id="llm-fixture-test-001",
                        confirmation="NO",
                    )
                )
        build_provider.assert_not_called()

    def test_success_records_only_validated_intent_and_zero_database_actions(self) -> None:
        settings = AppSettings(
            mysql_password="isolated-test-password",
            llm_provider="deepseek",
            llm_api_key="local-test-deepseek-key-001",
        )

        class FakeProvider:
            async def classify_intent(self, text: str) -> LLMResult:
                self.text = text
                return LLMResult(
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    prompt_version="prompt-v1",
                    payload={"intent": "BOOK_RECOMMENDATION"},
                    prompt_id="intent.classify",
                    prompt_sha256="a" * 64,
                    request_id="fixture-request",
                    attempts=1,
                )

        provider = FakeProvider()
        with patch.object(fixture_call, "AppSettings", return_value=settings), patch.object(
            fixture_call, "build_llm_provider", return_value=provider
        ), patch.object(
            fixture_call, "DeepSeekLLMProvider", FakeProvider
        ), patch.object(
            fixture_call,
            "_write_report",
            return_value=PROJECT_ROOT / "artifacts/verification/llm/test-real-call.json",
        ):
            report = asyncio.run(
                fixture_call.execute(
                    env_file=PROJECT_ROOT / "README.md",
                    run_id="llm-fixture-test-002",
                    confirmation="YES_REAL_EXTERNAL_LLM",
                )
            )

        self.assertEqual("PASS", report["status"])
        self.assertEqual("BOOK_RECOMMENDATION", report["result"]["intent"])
        self.assertEqual(0, report["safety"]["database_writes"])
        self.assertEqual(0, report["safety"]["outbox_claims"])

    def test_explanation_records_validated_shape_without_generated_prose(self) -> None:
        settings = AppSettings(
            mysql_password="isolated-test-password",
            llm_provider="deepseek",
            llm_api_key="local-test-deepseek-key-001",
        )

        class FakeProvider:
            async def render_explanation(self, evidence: dict[str, object]) -> LLMResult:
                self.evidence = evidence
                return LLMResult(
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    prompt_version="prompt-v1",
                    payload={
                        "text": "该资源与主题匹配 [resource:book:6452]。",
                        "evidence_refs": ["resource:book:6452"],
                    },
                    prompt_id="explanation.render",
                    prompt_sha256="b" * 64,
                    request_id="explanation-fixture-request",
                    attempts=1,
                )

        provider = FakeProvider()
        with patch.object(fixture_call, "AppSettings", return_value=settings), patch.object(
            fixture_call, "build_llm_provider", return_value=provider
        ), patch.object(
            fixture_call, "DeepSeekLLMProvider", FakeProvider
        ), patch.object(
            fixture_call,
            "_write_report",
            return_value=PROJECT_ROOT / "artifacts/verification/llm/test-explanation-call.json",
        ):
            report = asyncio.run(
                fixture_call.execute(
                    env_file=PROJECT_ROOT / "README.md",
                    run_id="llm-fixture-test-003",
                    confirmation="YES_REAL_EXTERNAL_LLM",
                    capability="explanation",
                )
            )

        self.assertEqual("PASS", report["status"])
        self.assertEqual("explanation", report["fixture"]["capability"])
        self.assertEqual(["resource:book:6452"], report["result"]["evidence_refs"])
        self.assertTrue(report["result"]["all_evidence_markers_present"])
        self.assertNotIn("text", report["result"])
        self.assertEqual(0, report["safety"]["database_writes"])

    def test_unknown_capability_is_rejected_before_provider_construction(self) -> None:
        with patch.object(fixture_call, "build_llm_provider") as build_provider:
            with self.assertRaises(ValueError):
                asyncio.run(
                    fixture_call.execute(
                        env_file=PROJECT_ROOT / "README.md",
                        run_id="llm-fixture-test-004",
                        confirmation="YES_REAL_EXTERNAL_LLM",
                        capability="unknown",
                    )
                )
        build_provider.assert_not_called()


if __name__ == "__main__":
    unittest.main()
