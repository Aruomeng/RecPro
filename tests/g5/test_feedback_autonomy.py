from __future__ import annotations

import unittest

from backend.app.feedback.application.autonomy import (
    FeedbackLearningAgent,
    FeedbackLearningObservation,
)
from backend.app.shared_kernel.contracts.autonomy import validate_decision
from backend.app.shared_kernel.contracts.enums import AgentActionType


class FeedbackLearningAutonomyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = FeedbackLearningAgent()

    def test_pending_profile_update_proposes_bounded_delta(self) -> None:
        decision = self.agent.decide(
            FeedbackLearningObservation(
                event_type="NOT_INTERESTED",
                replayed=False,
                profile_update_pending=True,
                state_type="HIDDEN",
            )
        )
        self.assertEqual(AgentActionType.PROPOSE_PROFILE_DELTA, decision.action)
        self.assertEqual("UserProfileAgent", decision.target)
        self.assertEqual("NEGATIVE_SIGNAL", decision.parameters["adjustment"])
        self.assertIs(validate_decision("FeedbackLearningAgent", decision), decision)

    def test_replay_returns_without_proposing_a_second_delta(self) -> None:
        decision = self.agent.decide(
            FeedbackLearningObservation(
                event_type="NOT_INTERESTED",
                replayed=True,
                profile_update_pending=True,
                state_type="HIDDEN",
            )
        )
        self.assertEqual(AgentActionType.RETURN_RESULT, decision.action)
        self.assertEqual("IDEMPOTENT_REPLAY", decision.reason_code)
        self.assertEqual("RecommendationOrchestrator", decision.target)

    def test_no_pending_update_returns_a_safe_noop_action(self) -> None:
        public = self.agent.public_decision(
            FeedbackLearningObservation(
                event_type="RECOMMENDATION_IMPRESSION",
                replayed=False,
                profile_update_pending=False,
            )
        )
        self.assertEqual("FeedbackLearningAgent", public["agent_name"])
        self.assertEqual("RETURN_RESULT", public["action"])
        self.assertEqual("NO_PROFILE_DELTA_REQUIRED", public["reason_code"])


if __name__ == "__main__":
    unittest.main()
