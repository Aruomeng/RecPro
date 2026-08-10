from __future__ import annotations

from unittest.mock import AsyncMock, patch
import unittest

from pydantic import SecretStr

from backend.app.llm.adapters.deepseek import DeepSeekLLMProvider
from backend.app.llm.adapters.mock import MockLLMProvider
from backend.app.llm.factory import build_llm_provider
from backend.app.config import AppSettings


class DeepSeekLLMProviderTest(unittest.IsolatedAsyncioTestCase):
    def _provider(self) -> DeepSeekLLMProvider:
        return DeepSeekLLMProvider(api_key=SecretStr("local-test-deepseek-key-001"))

    def test_construction_fails_closed_without_key_or_https_origin(self) -> None:
        with self.assertRaises(ValueError):
            DeepSeekLLMProvider(api_key=SecretStr(""))
        with self.assertRaises(ValueError):
            DeepSeekLLMProvider(
                api_key=SecretStr("local-test-deepseek-key-001"),
                base_url="http://127.0.0.1:9000",
            )

    async def test_intent_result_is_strictly_mapped_without_network(self) -> None:
        provider = self._provider()
        with patch.object(
            DeepSeekLLMProvider,
            "_complete",
            new=AsyncMock(return_value={"intent": "BOOK_RECOMMENDATION"}),
        ) as complete:
            result = await provider.classify_intent("请推荐智慧图书馆相关图书")

        complete.assert_awaited_once()
        self.assertEqual("deepseek", result.provider)
        self.assertEqual("BOOK_RECOMMENDATION", result.payload["intent"])

    async def test_invalid_model_output_is_rejected(self) -> None:
        provider = self._provider()
        with patch.object(
            DeepSeekLLMProvider,
            "_complete",
            new=AsyncMock(return_value={"intent": "UNSAFE"}),
        ):
            with self.assertRaises(ValueError):
                await provider.classify_intent("topic")

    def test_factory_keeps_mock_default_and_does_not_call_network(self) -> None:
        settings = AppSettings(mysql_password="isolated-test-password")
        provider = build_llm_provider(settings)
        self.assertIsInstance(provider, MockLLMProvider)

    def test_factory_builds_deepseek_only_from_validated_settings(self) -> None:
        settings = AppSettings(
            mysql_password="isolated-test-password",
            llm_provider="deepseek",
            llm_api_key="local-test-deepseek-key-001",
        )
        provider = build_llm_provider(settings)
        self.assertIsInstance(provider, DeepSeekLLMProvider)


if __name__ == "__main__":
    unittest.main()
