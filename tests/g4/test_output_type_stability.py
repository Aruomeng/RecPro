from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import unittest
from uuid import uuid4

from backend.app.recommendation.agents.rule_agents import RuleRecommendationPolicyAgent
from backend.app.recommendation.domain.output_type_stability import (
    infer_auto_output_type,
    stabilize_output_type,
)
from backend.app.shared_kernel.contracts.agent import AgentMessage
from backend.app.shared_kernel.contracts.enums import MessageType, OutputType


def policy_message(*, payload: dict[str, object]) -> AgentMessage:
    now = datetime.now(UTC)
    return AgentMessage(
        schema_version="g4-orchestrator-v1",
        message_id=uuid4(),
        trace_id=uuid4(),
        task_id=uuid4(),
        sender="RecommendationOrchestrator",
        receiver="RecommendationPolicyAgent",
        message_type=MessageType.POLICY_DECIDE,
        payload=payload,
        deadline_at=now + timedelta(seconds=3),
        idempotency_key=str(uuid4()),
        context_version=1,
        created_at=now,
    )


class OutputTypeStabilityTests(unittest.TestCase):
    def test_near_threshold_sequence_holds_for_two_rounds_then_switches(self) -> None:
        previous: str | None = None
        rounds = 0
        decisions = []
        for strength in (0.65, 0.64, 0.64, 0.54):
            proposed = infer_auto_output_type(
                intent_type="GENERAL_RECOMMENDATION",
                topic_focus_strength=strength,
            )
            decision = stabilize_output_type(
                proposed_output_type=proposed,
                topic_focus_strength=strength,
                previous_output_type=previous,
                previous_rounds=rounds,
            )
            decisions.append(decision)
            previous, rounds = decision.output_type, decision.rounds

        self.assertEqual(OutputType.TOPIC_RESOURCES.value, decisions[0].output_type)
        self.assertEqual("AUTO_OUTPUT_TYPE_HOLD_MIN_ROUNDS", decisions[1].reason_code)
        self.assertEqual(OutputType.TOPIC_RESOURCES.value, decisions[1].output_type)
        self.assertEqual("AUTO_OUTPUT_TYPE_HYSTERESIS_HOLD", decisions[2].reason_code)
        self.assertEqual(OutputType.TOPIC_RESOURCES.value, decisions[2].output_type)
        self.assertEqual("AUTO_OUTPUT_TYPE_SWITCH", decisions[3].reason_code)
        self.assertEqual(OutputType.PERSONALIZED_FEED.value, decisions[3].output_type)
        self.assertEqual((1, 2, 3, 1), tuple(item.rounds for item in decisions))

    def test_explicit_output_type_overrides_stability_immediately(self) -> None:
        decision = stabilize_output_type(
            proposed_output_type=OutputType.PERSONALIZED_FEED.value,
            topic_focus_strength=0.64,
            previous_output_type=OutputType.TOPIC_RESOURCES.value,
            previous_rounds=1,
            explicit_output_type=OutputType.BOOKLIST.value,
        )
        self.assertEqual(OutputType.BOOKLIST.value, decision.output_type)
        self.assertEqual("EXPLICIT_OUTPUT_TYPE_OVERRIDE", decision.reason_code)
        self.assertTrue(decision.changed)
        self.assertEqual(1, decision.rounds)
        self.assertTrue(decision.explicit_override)

    def test_rule_policy_emits_stability_reason_and_accepts_explicit_override(self) -> None:
        base_payload = {
            "intent": {"intent_type": "GENERAL_RECOMMENDATION"},
            "profile": {"topic_focus_strength": 0.64},
            "probe": {"metadata_coverage": 1.0},
            "constraints": {
                "previous_output_type": OutputType.TOPIC_RESOURCES.value,
                "previous_output_type_rounds": 2,
            },
            "output_type": None,
        }
        agent = RuleRecommendationPolicyAgent()
        held = asyncio.run(agent.handle(policy_message(payload=base_payload)))
        self.assertEqual(OutputType.TOPIC_RESOURCES.value, held.payload["output_type"])
        self.assertIn("AUTO_OUTPUT_TYPE_HYSTERESIS_HOLD", held.payload["decision_reason_codes"])
        self.assertEqual(3, held.payload["output_type_rounds"])

        overridden_payload = {
            **base_payload,
            "output_type": OutputType.READING_PATH.value,
        }
        overridden = asyncio.run(
            agent.handle(policy_message(payload=overridden_payload))
        )
        self.assertEqual(OutputType.READING_PATH.value, overridden.payload["output_type"])
        self.assertIn(
            "EXPLICIT_OUTPUT_TYPE_OVERRIDE",
            overridden.payload["decision_reason_codes"],
        )
        self.assertEqual(1, overridden.payload["output_type_rounds"])
        self.assertTrue(overridden.payload["explicit_output_type_override"])


if __name__ == "__main__":
    unittest.main()
