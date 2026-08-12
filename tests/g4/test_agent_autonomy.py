from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID
import unittest

from backend.app.recommendation.agents.autonomy import (
    AgentAutonomyError,
    ROLE_PROFILES,
    validate_decision,
)
from backend.app.recommendation.agents.orchestrator import OrchestrationRequest
from backend.app.recommendation.application.orchestration import build_rule_orchestrator
from backend.app.shared_kernel.contracts.agent import AgentDecision
from backend.app.shared_kernel.contracts.enums import AgentActionType, TaskStatus


class AgentAutonomyContractTests(unittest.TestCase):
    def request(self, **overrides: object) -> OrchestrationRequest:
        values: dict[str, object] = {
            "task_id": UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            "trace_id": UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
            "session_id": UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"),
            "user_id": 1001,
            "input_text": "多智能体推荐",
            "resource_types": ("BOOK", "PAPER"),
            "deadline_at": datetime.now(UTC) + timedelta(seconds=30),
        }
        values.update(overrides)
        return OrchestrationRequest(**values)  # type: ignore[arg-type]

    def test_every_registered_role_has_goal_observation_tools_and_actions(self) -> None:
        self.assertEqual(8, len(ROLE_PROFILES))
        for profile in ROLE_PROFILES.values():
            self.assertTrue(profile.role)
            self.assertTrue(profile.goal)
            self.assertTrue(profile.observations)
            self.assertTrue(profile.tools)
            self.assertTrue(profile.allowed_actions)
            self.assertIn(AgentActionType.RETURN_RESULT, profile.allowed_actions)

    def test_role_cannot_propose_another_agents_action(self) -> None:
        with self.assertRaises(AgentAutonomyError):
            validate_decision(
                "RankingAgent",
                AgentDecision(
                    action=AgentActionType.ASK_CLARIFICATION,
                    target="User",
                    reason_code="NOT_ALLOWED",
                    confidence=0.8,
                ),
            )

    def test_direct_path_trace_contains_local_actions(self) -> None:
        result = asyncio.run(build_rule_orchestrator().run(self.request()))
        actions = [step["autonomy"]["action"] for step in result.trace]
        self.assertIn("PLAN_RECALL", actions)
        self.assertIn("SELECT_CHANNELS", actions)
        self.assertIn("RENDER_EVIDENCE", actions)

    def test_guided_path_is_chosen_by_policy_action(self) -> None:
        result = asyncio.run(
            build_rule_orchestrator().run(
                self.request(input_text=None, resource_types=())
            )
        )
        self.assertEqual(TaskStatus.WAITING_CLARIFICATION, result.status)
        policy_step = next(
            step for step in result.trace if step["agent_name"] == "RecommendationPolicyAgent"
        )
        self.assertEqual("ASK_CLARIFICATION", policy_step["autonomy"]["action"])

    def test_ranking_requests_at_most_one_replan(self) -> None:
        result = asyncio.run(
            build_rule_orchestrator().run(
                self.request(constraints={"force_replan": True})
            )
        )
        actions = [step["autonomy"]["action"] for step in result.trace]
        self.assertEqual(1, actions.count("REQUEST_REPLAN"))
        self.assertEqual(1, result.replan_count)


if __name__ == "__main__":
    unittest.main()
