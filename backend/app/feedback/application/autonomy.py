"""Bounded FeedbackLearningAgent decisions for the explicit interaction edge.

This Agent observes only the normalized receipt outcome.  It never opens a
connection, claims an Outbox row, or mutates a profile; its finite decision is
returned to the HTTP boundary for audit and later orchestration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.app.shared_kernel.contracts.agent import AgentDecision
from backend.app.shared_kernel.contracts.autonomy import validate_decision
from backend.app.shared_kernel.contracts.enums import AgentActionType


@dataclass(frozen=True, slots=True)
class FeedbackLearningObservation:
    event_type: str
    replayed: bool
    profile_update_pending: bool
    state_type: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.event_type, str) or not self.event_type.strip():
            raise ValueError("event_type must be non-blank")
        if not isinstance(self.replayed, bool):
            raise ValueError("replayed must be boolean")
        if not isinstance(self.profile_update_pending, bool):
            raise ValueError("profile_update_pending must be boolean")
        if self.state_type is not None and (
            not isinstance(self.state_type, str) or not self.state_type.strip()
        ):
            raise ValueError("state_type must be null or non-blank")


class FeedbackLearningAgent:
    """Choose a bounded next action from one interaction receipt."""

    name = "FeedbackLearningAgent"
    version = "feedback-edge-v1"

    def decide(self, observation: FeedbackLearningObservation) -> AgentDecision:
        if observation.replayed:
            return validate_decision(
                self.name,
                AgentDecision(
                    action=AgentActionType.RETURN_RESULT,
                    target="RecommendationOrchestrator",
                    reason_code="IDEMPOTENT_REPLAY",
                    confidence=0.96,
                    parameters={
                        "event_type": observation.event_type,
                        "replayed": True,
                    },
                ),
            )
        if observation.profile_update_pending:
            adjustment = (
                "NEGATIVE_SIGNAL"
                if observation.state_type in {"HIDDEN", "READ", "DUPLICATE_SUPPRESS", "NOT_NOW"}
                else "POSITIVE_OR_NEUTRAL_SIGNAL"
            )
            return validate_decision(
                self.name,
                AgentDecision(
                    action=AgentActionType.PROPOSE_PROFILE_DELTA,
                    target="UserProfileAgent",
                    reason_code="PROFILE_DELTA_QUEUED",
                    confidence=0.84,
                    parameters={
                        "event_type": observation.event_type,
                        "profile_update": "PENDING",
                        "adjustment": adjustment,
                    },
                ),
            )
        return validate_decision(
            self.name,
            AgentDecision(
                action=AgentActionType.RETURN_RESULT,
                target="RecommendationOrchestrator",
                reason_code="NO_PROFILE_DELTA_REQUIRED",
                confidence=0.82,
                parameters={"event_type": observation.event_type},
            ),
        )

    def public_decision(self, observation: FeedbackLearningObservation) -> dict[str, Any]:
        """Return a transport-safe decision without exposing raw interaction data."""

        return {
            "agent_name": self.name,
            "agent_version": self.version,
            **self.decide(observation).as_dict(),
        }


def feedback_learning_decision(
    *,
    event_type: str,
    replayed: bool,
    profile_update_pending: bool,
    state_type: str | None = None,
) -> dict[str, Any]:
    """Build one public action for an interaction receipt."""

    return FeedbackLearningAgent().public_decision(
        FeedbackLearningObservation(
            event_type=event_type,
            replayed=replayed,
            profile_update_pending=profile_update_pending,
            state_type=state_type,
        )
    )


__all__ = [
    "FeedbackLearningAgent",
    "FeedbackLearningObservation",
    "feedback_learning_decision",
]
