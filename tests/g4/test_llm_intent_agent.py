from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
import unittest
from uuid import uuid4

from backend.app.llm.adapters.mock import MockFailureMode, MockLLMProvider
from backend.app.recommendation.agents.llm_agents import LLMIntentUnderstandingAgent
from backend.app.shared_kernel.contracts.agent import AgentMessage
from backend.app.shared_kernel.contracts.enums import AgentResultStatus, MessageType


def message(*, input_text: str | None, deadline: bool = True) -> AgentMessage:
    now = datetime.now(UTC)
    return AgentMessage(
        schema_version="g4-orchestrator-v1",
        message_id=uuid4(),
        trace_id=uuid4(),
        task_id=uuid4(),
        sender="RecommendationOrchestrator",
        receiver="IntentUnderstandingAgent",
        message_type=MessageType.INTENT_RESOLVE,
        payload={"input_text": input_text, "resource_types": ["BOOK"]},
        deadline_at=now + timedelta(seconds=2) if deadline else None,
        attempt=1,
        idempotency_key=str(uuid4()),
        context_version=1,
        created_at=now,
    )


class LLMIntentAgentTest(unittest.IsolatedAsyncioTestCase):
    async def test_provider_is_opt_in_and_only_classifies(self) -> None:
        result = await LLMIntentUnderstandingAgent(
            MockLLMProvider()
        ).handle(message(input_text="请推荐多智能体论文"))
        self.assertEqual("intent-llm-prompt-v1", result.agent_version)
        self.assertEqual("TOPIC_RECOMMENDATION", result.payload["intent_type"])
        self.assertFalse(result.fallback_used)
        self.assertEqual("LLM_CLASSIFICATION", result.payload["reason_codes"][0])
        self.assertEqual("mock", result.payload["llm_provider"])
        self.assertEqual("intent.classify", result.payload["prompt_id"])
        self.assertTrue(result.evidence_refs[0].startswith("llm:intent.classify:"))

    async def test_provider_failure_returns_rule_fallback_without_raising(self) -> None:
        provider = MockLLMProvider(failure_mode=MockFailureMode.ERROR)
        result = await LLMIntentUnderstandingAgent(provider).handle(
            message(input_text="推荐图书")
        )
        self.assertTrue(result.fallback_used)
        self.assertEqual(AgentResultStatus.PARTIAL, result.status)
        self.assertIsNone(result.error_code)
        self.assertIn("LLM_INTENT_FALLBACK", result.warnings)
        self.assertEqual("LLM_INTENT_PROVIDER_UNAVAILABLE", result.payload["llm_fallback_reason_code"])
        self.assertEqual("LLM_INTENT_PROVIDER_UNAVAILABLE", result.decision.reason_code)
        self.assertEqual("TOPIC_RECOMMENDATION", result.payload["intent_type"])

    async def test_empty_input_never_calls_provider(self) -> None:
        provider = AsyncMock()
        result = await LLMIntentUnderstandingAgent(provider).handle(
            message(input_text=None)
        )
        provider.classify_intent.assert_not_awaited()
        self.assertTrue(result.fallback_used)
        self.assertIn("LLM_INTENT_SKIPPED_EMPTY_INPUT", result.warnings)

    async def test_explicitly_uncertain_goal_skips_provider_and_requests_clarification(self) -> None:
        provider = AsyncMock()
        result = await LLMIntentUnderstandingAgent(provider).handle(
            message(input_text="我还不确定要研究什么，先帮我梳理方向")
        )
        provider.classify_intent.assert_not_awaited()
        self.assertEqual("UNCLEAR", result.payload["intent_type"])
        self.assertEqual("ASK_CLARIFICATION", result.decision.action.value)
        self.assertTrue(result.fallback_used)
        self.assertIn("LLM_INTENT_SKIPPED_AMBIGUOUS_INPUT", result.warnings)

    async def test_bad_provider_payload_falls_back(self) -> None:
        provider = AsyncMock()
        provider.classify_intent.return_value = type(
            "Result", (), {"payload": {"intent": "UNSAFE"}, "prompt_id": "intent.classify", "prompt_sha256": "x"}
        )()
        result = await LLMIntentUnderstandingAgent(provider).handle(
            message(input_text="topic")
        )
        self.assertTrue(result.fallback_used)
        self.assertIsNone(result.error_code)
        self.assertEqual("LLM_INTENT_OUTPUT_REJECTED", result.payload["llm_fallback_reason_code"])


if __name__ == "__main__":
    unittest.main()
