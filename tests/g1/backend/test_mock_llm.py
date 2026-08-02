from __future__ import annotations

import unittest

from backend.app.llm.adapters.mock import MockFailureMode, MockLLMProvider


class MockLLMProviderTest(unittest.IsolatedAsyncioTestCase):
    async def test_same_input_is_deterministic_and_has_provider_metadata(self) -> None:
        provider = MockLLMProvider()
        first = await provider.classify_intent("请推荐多智能体论文")
        second = await provider.classify_intent("请推荐多智能体论文")

        self.assertEqual(first, second)
        self.assertEqual("PAPER_RECOMMENDATION", first.payload["intent"])
        self.assertEqual("mock", first.provider)
        self.assertEqual("mock-v1", first.model)
        self.assertEqual("mock-prompt-v1", first.prompt_version)

    async def test_explanation_uses_only_supplied_evidence(self) -> None:
        result = await MockLLMProvider().render_explanation(
            {"factors": ["主题匹配", "用户近期阅读"]}
        )

        self.assertEqual("主题匹配；用户近期阅读", result.payload["text"])
        self.assertFalse(result.payload["evidence_limited"])

    async def test_feedback_has_conservative_fallback(self) -> None:
        result = await MockLLMProvider().parse_feedback_text("暂时不确定")
        self.assertEqual("OTHER", result.payload["reason_code"])

    async def test_fault_modes_are_explicit(self) -> None:
        cases = (
            (MockFailureMode.TIMEOUT, TimeoutError),
            (MockFailureMode.INVALID_PAYLOAD, ValueError),
            (MockFailureMode.ERROR, RuntimeError),
        )
        for mode, expected_error in cases:
            with self.subTest(mode=mode):
                with self.assertRaises(expected_error):
                    await MockLLMProvider(failure_mode=mode).classify_intent("topic")
