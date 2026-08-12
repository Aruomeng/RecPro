from __future__ import annotations

import asyncio
import unittest
from datetime import UTC, datetime, timedelta
from uuid import UUID

from backend.app.recommendation.application.orchestration import build_rule_orchestrator
from backend.app.recommendation.agents.orchestrator import OrchestrationRequest
from backend.app.recommendation.agents.registry import AgentRegistry, AgentUnavailableError
from backend.app.recommendation.agents.rule_agents import DEFAULT_RULE_AGENTS
from backend.app.shared_kernel.contracts.enums import TaskStatus


class G4OrchestratorTest(unittest.TestCase):
    def request(
        self,
        *,
        input_text: str | None = "多智能体推荐",
        resource_types=("BOOK", "PAPER"),
        output_type: str | None = None,
        constraints=None,
        context_version: int = 1,
        initial_status: TaskStatus = TaskStatus.CREATED,
    ) -> OrchestrationRequest:
        return OrchestrationRequest(
            task_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            trace_id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
            session_id=UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"),
            user_id=1001,
            input_text=input_text,
            resource_types=resource_types,
            output_type=output_type,
            constraints=constraints,
            context_version=context_version,
            deadline_at=datetime.now(UTC) + timedelta(seconds=30),
            initial_status=initial_status,
        )

    def execute(self, request: OrchestrationRequest):
        return asyncio.run(build_rule_orchestrator().run(request))

    def test_registry_is_explicit_and_sorted(self) -> None:
        registry = AgentRegistry({agent.name: agent for agent in DEFAULT_RULE_AGENTS})
        self.assertEqual(8, len(registry.names))
        self.assertEqual(tuple(sorted(registry.names)), registry.names)
        with self.assertRaises(AgentUnavailableError):
            registry.resolve("UnknownAgent")

    def test_direct_path_runs_recall_rank_explanation_and_is_reproducible(self) -> None:
        first = self.execute(self.request())
        second = self.execute(self.request())
        self.assertEqual(TaskStatus.COMPLETED, first.status)
        self.assertEqual(0, first.replan_count)
        self.assertEqual(first.payload, second.payload)
        self.assertEqual(first.trace, second.trace)
        self.assertIn("Recall", " ".join(step["agent_name"] for step in first.trace))
        self.assertIn("RankingAgent", {step["agent_name"] for step in first.trace})
        self.assertIn("ExplanationAgent", {step["agent_name"] for step in first.trace})
        self.assertEqual("COMPLETED", first.payload["status"])

    def test_unclear_path_stops_at_guided_before_recall(self) -> None:
        result = self.execute(self.request(input_text=None, resource_types=()))
        self.assertEqual(TaskStatus.WAITING_CLARIFICATION, result.status)
        self.assertEqual("GUIDED", result.payload["decision"]["delivery_strategy"])
        self.assertEqual(2, len(result.payload["questions"]))
        self.assertNotIn("CandidateRecallAgent", {step["agent_name"] for step in result.trace})
        self.assertNotIn("RankingAgent", {step["agent_name"] for step in result.trace})
        self.assertEqual("WAITING_CLARIFICATION", result.transitions[-1]["to_status"])

    def test_continuation_starts_from_waiting_context(self) -> None:
        result = self.execute(self.request(initial_status=TaskStatus.WAITING_CLARIFICATION, context_version=2))
        self.assertEqual(TaskStatus.COMPLETED, result.status)
        self.assertEqual(2, result.context_version)
        self.assertEqual("WAITING_CLARIFICATION", result.transitions[0]["from_status"])
        self.assertEqual("UNDERSTANDING", result.transitions[0]["to_status"])

    def test_degraded_path_preserves_results_and_warnings(self) -> None:
        result = self.execute(self.request(constraints={"force_degraded": True}))
        self.assertEqual(TaskStatus.DEGRADED_COMPLETED, result.status)
        self.assertEqual("DEGRADED", result.payload["decision"]["delivery_strategy"])
        self.assertIn("VECTOR_CHANNEL_UNAVAILABLE", result.payload["warnings"])
        self.assertGreaterEqual(len(result.payload["items"]), 1)
        self.assertTrue(result.payload["agent_results"]["CandidateRecallAgent"]["fallback_used"])

    def test_reading_path_with_one_difficulty_level_is_degraded_without_fake_stages(self) -> None:
        result = self.execute(
            self.request(
                input_text="系统学习多智能体",
                resource_types=("BOOK",),
                output_type="READING_PATH",
                constraints={"covered_difficulty_levels": 1},
            )
        )
        self.assertEqual(TaskStatus.DEGRADED_COMPLETED, result.status)
        decision = result.payload["decision"]
        self.assertEqual("READING_PATH", decision["output_type"])
        self.assertEqual("DEGRADED", decision["delivery_strategy"])
        self.assertIn("READING_PATH_SINGLE_DIFFICULTY", decision["decision_reason_codes"])
        self.assertIn("READING_PATH_SINGLE_DIFFICULTY", result.payload["warnings"])
        self.assertNotIn("VECTOR_CHANNEL_UNAVAILABLE", result.payload["warnings"])
        self.assertNotIn("KG_CHANNEL_UNAVAILABLE", result.payload["warnings"])
        self.assertIn("READING_PATH_DEGRADED", decision["decision_reason_codes"])
        self.assertIn("不伪造", decision["decision_reason"])
        self.assertTrue(all("reading_stage" not in item for item in result.payload["items"]))

    def test_replanning_is_bounded_to_one_and_has_distinct_trace(self) -> None:
        result = self.execute(self.request(constraints={"force_replan": True}))
        self.assertEqual(TaskStatus.COMPLETED, result.status)
        self.assertEqual(1, result.replan_count)
        self.assertIn("REPLANNING", {transition["to_status"] for transition in result.transitions})
        message_types = [step["message_type"] for step in result.trace]
        self.assertIn("POLICY.REPLAN", message_types)
        self.assertGreaterEqual(message_types.count("RECALL.EXECUTE"), 2)
        self.assertGreaterEqual(message_types.count("RANK.EXECUTE"), 2)


if __name__ == "__main__":
    unittest.main()
