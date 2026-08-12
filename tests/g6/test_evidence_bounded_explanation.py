from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from uuid import UUID

from backend.app.llm.ports.public import LLMResult
from backend.app.recommendation.agents.llm_agents import LLMExplanationAgent
from backend.app.shared_kernel.contracts.agent import AgentMessage
from backend.app.shared_kernel.contracts.enums import MessageType


class FaultInjectingExplanationProvider:
    """Return a fabricated evidence reference to exercise the fail-closed path."""

    def __init__(self) -> None:
        self.calls = 0

    async def render_explanation(self, evidence: dict[str, object]) -> LLMResult:
        self.calls += 1
        return LLMResult(
            provider="fault-injecting",
            model="fault-model",
            prompt_version="fault-prompt-v1",
            payload={
                "text": "该资源来自不存在的行为事实 [behavior:999]。",
                "evidence_refs": ["behavior:999"],
            },
            prompt_id="explanation.render",
            attempts=1,
        )


def explanation_message() -> AgentMessage:
    created_at = datetime(2026, 8, 12, 8, 0, tzinfo=UTC)
    return AgentMessage(
        schema_version="g4-orchestrator-v1",
        message_id=UUID("11111111-1111-1111-1111-111111111111"),
        trace_id=UUID("22222222-2222-2222-2222-222222222222"),
        task_id=UUID("33333333-3333-3333-3333-333333333333"),
        sender="RecommendationOrchestrator",
        receiver="ExplanationAgent",
        message_type=MessageType.EXPLAIN_EXECUTE,
        payload={
            "ranked_items": [
                {
                    "resource_id": 7,
                    "rank_no": 1,
                    "channel": "MYSQL+GRAPH",
                    "evidence_ref": "catalog:resource:7:metadata:v1:graph:g1",
                }
            ]
        },
        deadline_at=created_at + timedelta(seconds=5),
        idempotency_key="explanation-fault-001",
        context_version=1,
        created_at=created_at,
    )


class EvidenceBoundedExplanationTests(unittest.IsolatedAsyncioTestCase):
    async def test_invented_evidence_fails_validation_and_returns_template(self) -> None:
        provider = FaultInjectingExplanationProvider()

        result = await LLMExplanationAgent(provider).handle(explanation_message())

        self.assertEqual(1, provider.calls)
        self.assertEqual("ExplanationAgent", result.agent_name)
        self.assertEqual("PARTIAL", result.status.value)
        self.assertTrue(result.fallback_used)
        self.assertIn("EVIDENCE_VALIDATION_FAILED", result.warnings)
        self.assertIn("LLM_EXPLANATION_FALLBACK", result.warnings)
        explanation = result.payload["explanations"][0]
        self.assertEqual(
            "基于已验证的目录证据生成推荐解释。",
            explanation["summary"],
        )
        self.assertEqual(
            ["catalog:resource:7:metadata:v1:graph:g1"],
            explanation["evidence_refs"],
        )
        self.assertEqual("TEMPLATE", result.payload["provider"])


if __name__ == "__main__":
    unittest.main()
