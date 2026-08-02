from __future__ import annotations

import unittest
from types import MappingProxyType
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from backend.app.shared_kernel.contracts.agent import AgentMessage, AgentResult, ArtifactRef
from backend.app.shared_kernel.contracts.enums import (
    AdaptationState,
    AgentResultStatus,
    DeliveryStrategy,
    ExplanationLevel,
    MessageType,
    OutputType,
    RecallChannel,
    ResourceType,
    TaskStatus,
)
from backend.app.shared_kernel.contracts.policy import (
    ClarificationQuestion,
    InteractionDecision,
    PolicyResult,
    RetrievalChannelPlan,
    RetrievalPlan,
)
from backend.app.shared_kernel.contracts.state import can_transition


class AgentMessageTest(unittest.TestCase):
    def test_valid_message_is_accepted(self) -> None:
        created_at = datetime(2026, 8, 2, tzinfo=timezone.utc)
        message = AgentMessage(
            schema_version="1.0.0",
            message_id=uuid4(),
            trace_id=uuid4(),
            task_id=uuid4(),
            sender="orchestrator",
            receiver="intent",
            message_type=MessageType.INTENT_RESOLVE,
            payload={"input_text": "多智能体推荐"},
            deadline_at=created_at + timedelta(seconds=2),
            idempotency_key="task-1:intent:1",
            context_version=1,
            created_at=created_at,
        )
        self.assertEqual(MessageType.INTENT_RESOLVE, message.message_type)

    def test_naive_time_is_rejected(self) -> None:
        created_at = datetime(2026, 8, 2)
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            AgentMessage(
                schema_version="1.0.0",
                message_id=uuid4(),
                trace_id=uuid4(),
                task_id=uuid4(),
                sender="orchestrator",
                receiver="intent",
                message_type=MessageType.INTENT_RESOLVE,
                payload={},
                deadline_at=created_at + timedelta(seconds=2),
                idempotency_key="task-1:intent:1",
                context_version=1,
                created_at=created_at,
            )

    def test_deadline_must_follow_creation(self) -> None:
        created_at = datetime(2026, 8, 2, tzinfo=timezone.utc)
        with self.assertRaisesRegex(ValueError, "later than"):
            AgentMessage(
                schema_version="1.0.0",
                message_id=uuid4(),
                trace_id=uuid4(),
                task_id=uuid4(),
                sender="orchestrator",
                receiver="intent",
                message_type=MessageType.INTENT_RESOLVE,
                payload={},
                deadline_at=created_at,
                idempotency_key="task-1:intent:1",
                context_version=1,
                created_at=created_at,
            )

    def test_message_type_string_is_rejected(self) -> None:
        created_at = datetime(2026, 8, 2, tzinfo=timezone.utc)
        with self.assertRaisesRegex(ValueError, "MessageType"):
            AgentMessage(
                schema_version="1.0.0",
                message_id=uuid4(),
                trace_id=uuid4(),
                task_id=uuid4(),
                sender="orchestrator",
                receiver="intent",
                message_type="INTENT.RESOLVE",  # type: ignore[arg-type]
                payload={},
                deadline_at=created_at + timedelta(seconds=2),
                idempotency_key="task-1:intent:1",
                context_version=1,
                created_at=created_at,
            )

    def test_message_payload_list_is_rejected(self) -> None:
        created_at = datetime(2026, 8, 2, tzinfo=timezone.utc)
        with self.assertRaisesRegex(ValueError, "JSON object"):
            AgentMessage(
                schema_version="1.0.0",
                message_id=uuid4(),
                trace_id=uuid4(),
                task_id=uuid4(),
                sender="orchestrator",
                receiver="intent",
                message_type=MessageType.INTENT_RESOLVE,
                payload=[],  # type: ignore[arg-type]
                deadline_at=created_at + timedelta(seconds=2),
                idempotency_key="task-1:intent:1",
                context_version=1,
                created_at=created_at,
            )

    def test_message_payload_nested_non_json_value_is_rejected(self) -> None:
        created_at = datetime(2026, 8, 2, tzinfo=timezone.utc)
        with self.assertRaisesRegex(ValueError, "JSON-compatible"):
            AgentMessage(
                schema_version="1.0.0",
                message_id=uuid4(),
                trace_id=uuid4(),
                task_id=uuid4(),
                sender="orchestrator",
                receiver="intent",
                message_type=MessageType.INTENT_RESOLVE,
                payload={"nested": {"raw_uuid": uuid4()}},
                deadline_at=created_at + timedelta(seconds=2),
                idempotency_key="task-1:intent:1",
                context_version=1,
                created_at=created_at,
            )

    def test_message_mapping_proxy_is_rejected_before_wire_encoding(self) -> None:
        created_at = datetime(2026, 8, 2, tzinfo=timezone.utc)
        with self.assertRaisesRegex(ValueError, "JSON object"):
            AgentMessage(
                schema_version="1.0.0",
                message_id=uuid4(),
                trace_id=uuid4(),
                task_id=uuid4(),
                sender="orchestrator",
                receiver="intent",
                message_type=MessageType.INTENT_RESOLVE,
                payload=MappingProxyType({"input_text": "topic"}),  # type: ignore[arg-type]
                deadline_at=created_at + timedelta(seconds=2),
                idempotency_key="task-1:intent:1",
                context_version=1,
                created_at=created_at,
            )


class AgentResultTest(unittest.TestCase):
    def test_success_requires_payload(self) -> None:
        with self.assertRaisesRegex(ValueError, "payload"):
            AgentResult[dict[str, str]](
                result_id=uuid4(),
                input_message_id=uuid4(),
                agent_name="intent",
                agent_version="1.0.0",
                status=AgentResultStatus.SUCCESS,
                confidence=0.9,
                payload=None,
            )

    def test_partial_requires_warning(self) -> None:
        with self.assertRaisesRegex(ValueError, "warning"):
            AgentResult[dict[str, str]](
                result_id=uuid4(),
                input_message_id=uuid4(),
                agent_name="intent",
                agent_version="1.0.0",
                status=AgentResultStatus.PARTIAL,
                confidence=0.5,
                payload={"intent": "UNCLEAR"},
            )

    def test_failure_cannot_include_business_payload(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not include"):
            AgentResult[dict[str, str]](
                result_id=uuid4(),
                input_message_id=uuid4(),
                agent_name="intent",
                agent_version="1.0.0",
                status=AgentResultStatus.FAILED,
                confidence=0.0,
                payload={"invented": "result"},
                error_code="INTENT_TIMEOUT",
            )

    def test_success_cannot_include_error_code(self) -> None:
        with self.assertRaisesRegex(ValueError, "only FAILED"):
            AgentResult[dict[str, str]](
                result_id=uuid4(),
                input_message_id=uuid4(),
                agent_name="intent",
                agent_version="1.0.0",
                status=AgentResultStatus.SUCCESS,
                confidence=0.9,
                payload={"intent": "TOPIC_RECOMMENDATION"},
                error_code="UNEXPECTED",
            )

    def test_result_status_string_cannot_bypass_failed_rules(self) -> None:
        with self.assertRaisesRegex(ValueError, "AgentResultStatus"):
            AgentResult[dict[str, str]](
                result_id=uuid4(),
                input_message_id=uuid4(),
                agent_name="intent",
                agent_version="1.0.0",
                status="FAILED",  # type: ignore[arg-type]
                confidence=0.0,
                payload={"invented": "result"},
            )

    def test_artifact_hash_must_be_sha256_hex(self) -> None:
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            ArtifactRef(uuid4(), "probe", "1.0.0", "abc")

    def test_result_payload_must_be_json_compatible(self) -> None:
        with self.assertRaisesRegex(ValueError, "JSON-compatible"):
            AgentResult[object](
                result_id=uuid4(),
                input_message_id=uuid4(),
                agent_name="intent",
                agent_version="1.0.0",
                status=AgentResultStatus.SUCCESS,
                confidence=0.9,
                payload={"generated_at": datetime.now(timezone.utc)},
            )

    def test_tool_calls_must_be_json_compatible(self) -> None:
        with self.assertRaisesRegex(ValueError, "JSON-compatible"):
            AgentResult[dict[str, str]](
                result_id=uuid4(),
                input_message_id=uuid4(),
                agent_name="intent",
                agent_version="1.0.0",
                status=AgentResultStatus.SUCCESS,
                confidence=0.9,
                payload={"intent": "TOPIC_RECOMMENDATION"},
                tool_calls=({"arguments": ("tuple-is-not-json-array",)},),
            )

    def test_tool_call_mapping_proxy_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "JSON-compatible dicts"):
            AgentResult[dict[str, str]](
                result_id=uuid4(),
                input_message_id=uuid4(),
                agent_name="intent",
                agent_version="1.0.0",
                status=AgentResultStatus.SUCCESS,
                confidence=0.9,
                payload={"intent": "TOPIC_RECOMMENDATION"},
                tool_calls=(MappingProxyType({"name": "probe"}),),  # type: ignore[arg-type]
            )

    def test_evidence_refs_must_be_unique(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicates"):
            AgentResult[dict[str, str]](
                result_id=uuid4(),
                input_message_id=uuid4(),
                agent_name="intent",
                agent_version="1.0.0",
                status=AgentResultStatus.SUCCESS,
                confidence=0.9,
                payload={"intent": "TOPIC_RECOMMENDATION"},
                evidence_refs=("evidence-1", "evidence-1"),
            )


class PolicyContractTest(unittest.TestCase):
    @staticmethod
    def _decision(strategy: DeliveryStrategy) -> InteractionDecision:
        return InteractionDecision(
            output_type=OutputType.TOPIC_RESOURCES,
            delivery_strategy=strategy,
            explanation_level=ExplanationLevel.EVIDENCE,
            adaptation_state=AdaptationState.NORMAL,
            decision_reason_codes=("EXPLICIT_TOPIC",),
            decision_reason="用户给出了明确主题",
            policy_version="policy-v1",
        )

    @staticmethod
    def _plan() -> RetrievalPlan:
        return RetrievalPlan(
            plan_version=1,
            min_candidates=20,
            resource_quotas={ResourceType.BOOK: 10, ResourceType.PAPER: 10},
            channels=(
                RetrievalChannelPlan(RecallChannel.KEYWORD, 20, 1000, True, 0.6),
                RetrievalChannelPlan(RecallChannel.TRENDING, 20, 1000, False, 0.4),
            ),
        )

    def test_guided_requires_questions(self) -> None:
        with self.assertRaisesRegex(ValueError, "questions"):
            PolicyResult(
                decision=self._decision(DeliveryStrategy.GUIDED),
                retrieval_plan=None,
            )

    def test_direct_requires_retrieval_plan(self) -> None:
        with self.assertRaisesRegex(ValueError, "retrieval plan"):
            PolicyResult(
                decision=self._decision(DeliveryStrategy.DIRECT),
                retrieval_plan=None,
            )

    def test_guided_contract_can_skip_retrieval(self) -> None:
        result = PolicyResult(
            decision=self._decision(DeliveryStrategy.GUIDED),
            retrieval_plan=None,
            clarification_questions=(
                ClarificationQuestion("topic", "你关注哪个主题？", ("多智能体", "推荐系统")),
            ),
        )
        self.assertIsNone(result.retrieval_plan)

    def test_guided_contract_rejects_retrieval_plan(self) -> None:
        with self.assertRaisesRegex(ValueError, "stop before"):
            PolicyResult(
                decision=self._decision(DeliveryStrategy.GUIDED),
                retrieval_plan=self._plan(),
                clarification_questions=(
                    ClarificationQuestion("topic", "你关注哪个主题？", ("多智能体",)),
                ),
            )

    def test_retrieval_weights_must_sum_to_one(self) -> None:
        with self.assertRaisesRegex(ValueError, "sum to 1"):
            RetrievalPlan(
                plan_version=1,
                min_candidates=20,
                resource_quotas={ResourceType.BOOK: 20},
                channels=(
                    RetrievalChannelPlan(
                        RecallChannel.KEYWORD,
                        20,
                        1000,
                        True,
                        0.8,
                    ),
                ),
            )

    def test_decision_enum_string_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "OutputType"):
            InteractionDecision(
                output_type="TOPIC_RESOURCES",  # type: ignore[arg-type]
                delivery_strategy=DeliveryStrategy.DIRECT,
                explanation_level=ExplanationLevel.EVIDENCE,
                adaptation_state=AdaptationState.NORMAL,
                decision_reason_codes=("EXPLICIT_TOPIC",),
                decision_reason="明确主题",
                policy_version="policy-v1",
            )

    def test_unknown_retrieval_channel_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "RecallChannel"):
            RetrievalChannelPlan(
                "MAGIC",  # type: ignore[arg-type]
                20,
                1000,
                True,
                1.0,
            )

    def test_clarification_required_must_be_boolean(self) -> None:
        with self.assertRaisesRegex(ValueError, "boolean"):
            ClarificationQuestion(
                "topic",
                "你关注哪个主题？",
                ("多智能体",),
                required="yes",  # type: ignore[arg-type]
            )


class RecommendationStateTest(unittest.TestCase):
    def test_normal_transition_is_allowed(self) -> None:
        self.assertTrue(
            can_transition(
                TaskStatus.CREATED,
                TaskStatus.UNDERSTANDING,
            )
        )

    def test_skip_transition_is_rejected(self) -> None:
        self.assertFalse(
            can_transition(
                TaskStatus.CREATED,
                TaskStatus.COMPLETED,
            )
        )

    def test_nonterminal_state_can_fail(self) -> None:
        self.assertTrue(
            can_transition(
                TaskStatus.RANKING,
                TaskStatus.FAILED,
            )
        )

    def test_terminal_state_cannot_transition(self) -> None:
        self.assertFalse(
            can_transition(
                TaskStatus.COMPLETED,
                TaskStatus.FAILED,
            )
        )


if __name__ == "__main__":
    unittest.main()
