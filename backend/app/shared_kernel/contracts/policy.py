"""Framework-independent interaction policy contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .enums import (
    AdaptationState,
    DeliveryStrategy,
    ExplanationLevel,
    OutputType,
    RecallChannel,
    ResourceType,
)


@dataclass(frozen=True, slots=True)
class InteractionDecision:
    output_type: OutputType
    delivery_strategy: DeliveryStrategy
    explanation_level: ExplanationLevel
    adaptation_state: AdaptationState
    decision_reason_codes: tuple[str, ...]
    decision_reason: str
    policy_version: str

    def __post_init__(self) -> None:
        enum_fields = (
            ("output_type", self.output_type, OutputType),
            ("delivery_strategy", self.delivery_strategy, DeliveryStrategy),
            ("explanation_level", self.explanation_level, ExplanationLevel),
            ("adaptation_state", self.adaptation_state, AdaptationState),
        )
        for field_name, value, enum_type in enum_fields:
            if not isinstance(value, enum_type):
                raise ValueError(f"{field_name} must be a {enum_type.__name__}")
        if not isinstance(self.decision_reason_codes, tuple) or not self.decision_reason_codes:
            raise ValueError("decision_reason_codes must not be empty")
        if not all(
            isinstance(code, str) and code.strip() for code in self.decision_reason_codes
        ):
            raise ValueError("decision_reason_codes must contain non-blank strings")
        if not isinstance(self.decision_reason, str) or not self.decision_reason.strip():
            raise ValueError("decision_reason must not be blank")
        if not isinstance(self.policy_version, str) or not self.policy_version.strip():
            raise ValueError("policy_version must not be blank")


@dataclass(frozen=True, slots=True)
class ClarificationQuestion:
    slot: str
    question: str
    options: tuple[str, ...]
    required: bool = True

    def __post_init__(self) -> None:
        if (
            not isinstance(self.slot, str)
            or not self.slot.strip()
            or not isinstance(self.question, str)
            or not self.question.strip()
        ):
            raise ValueError("slot and question must not be blank")
        if not isinstance(self.options, tuple) or not self.options:
            raise ValueError("clarification options must not be empty")
        if not all(isinstance(option, str) and option.strip() for option in self.options):
            raise ValueError("clarification options must contain non-blank strings")
        if not isinstance(self.required, bool):
            raise ValueError("required must be boolean")


@dataclass(frozen=True, slots=True)
class RetrievalChannelPlan:
    name: RecallChannel
    top_k: int
    timeout_ms: int
    required: bool
    weight: float

    def __post_init__(self) -> None:
        if not isinstance(self.name, RecallChannel):
            raise ValueError("channel name must be a RecallChannel")
        if (
            not isinstance(self.top_k, int)
            or isinstance(self.top_k, bool)
            or not isinstance(self.timeout_ms, int)
            or isinstance(self.timeout_ms, bool)
            or self.top_k < 1
            or self.timeout_ms < 1
        ):
            raise ValueError("top_k and timeout_ms must be positive")
        if not isinstance(self.required, bool):
            raise ValueError("required must be boolean")
        if not isinstance(self.weight, (int, float)) or isinstance(self.weight, bool):
            raise ValueError("weight must be numeric")
        if not 0.0 <= self.weight <= 1.0:
            raise ValueError("weight must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class RetrievalPlan:
    plan_version: int
    min_candidates: int
    resource_quotas: Mapping[ResourceType, int]
    channels: tuple[RetrievalChannelPlan, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.plan_version, int)
            or isinstance(self.plan_version, bool)
            or not isinstance(self.min_candidates, int)
            or isinstance(self.min_candidates, bool)
            or self.plan_version < 1
            or self.min_candidates < 1
        ):
            raise ValueError("plan_version and min_candidates must be positive")
        if not isinstance(self.resource_quotas, Mapping) or not all(
            isinstance(key, ResourceType)
            and isinstance(value, int)
            and not isinstance(value, bool)
            for key, value in self.resource_quotas.items()
        ):
            raise ValueError("resource_quotas must map ResourceType to integers")
        if not isinstance(self.channels, tuple) or not self.channels:
            raise ValueError("retrieval plan must contain at least one channel")
        if not all(isinstance(channel, RetrievalChannelPlan) for channel in self.channels):
            raise ValueError("channels must contain RetrievalChannelPlan values")
        if any(value < 0 for value in self.resource_quotas.values()):
            raise ValueError("resource quotas must not be negative")
        total_weight = sum(channel.weight for channel in self.channels)
        if abs(total_weight - 1.0) > 1e-9:
            raise ValueError("retrieval channel weights must sum to 1")


@dataclass(frozen=True, slots=True)
class PolicyResult:
    decision: InteractionDecision
    retrieval_plan: RetrievalPlan | None
    clarification_questions: tuple[ClarificationQuestion, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.decision, InteractionDecision):
            raise ValueError("decision must be an InteractionDecision")
        if self.retrieval_plan is not None and not isinstance(
            self.retrieval_plan, RetrievalPlan
        ):
            raise ValueError("retrieval_plan must be a RetrievalPlan or null")
        if not isinstance(self.clarification_questions, tuple) or not all(
            isinstance(question, ClarificationQuestion)
            for question in self.clarification_questions
        ):
            raise ValueError(
                "clarification_questions must contain ClarificationQuestion values"
            )
        guided = self.decision.delivery_strategy is DeliveryStrategy.GUIDED
        if guided and not self.clarification_questions:
            raise ValueError("GUIDED must include clarification questions")
        if guided and self.retrieval_plan is not None:
            raise ValueError("GUIDED must stop before a retrieval plan is created")
        if not guided and self.retrieval_plan is None:
            raise ValueError("non-GUIDED decisions must include a retrieval plan")
