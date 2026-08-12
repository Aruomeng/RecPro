"""Public recommendation domain values."""

from backend.app.recommendation.domain.models import (
    CandidateFeature,
    IntentResult,
    ProfileSignal,
    RecommendationExecution,
    RecommendationItemResult,
    RecommendationRequest,
    RecommendationTaskCommand,
    RecommendationTaskResult,
)
from backend.app.recommendation.domain.output_type_stability import (
    DEFAULT_HYSTERESIS_MARGIN,
    DEFAULT_MIN_OUTPUT_TYPE_ROUNDS,
    DEFAULT_TOPIC_FOCUS_INFER_THRESHOLD,
    OutputTypeStabilityDecision,
    infer_auto_output_type,
    stabilize_output_type,
)

__all__ = [
    "CandidateFeature",
    "IntentResult",
    "ProfileSignal",
    "RecommendationExecution",
    "RecommendationItemResult",
    "RecommendationRequest",
    "RecommendationTaskCommand",
    "RecommendationTaskResult",
    "OutputTypeStabilityDecision",
    "DEFAULT_HYSTERESIS_MARGIN",
    "DEFAULT_MIN_OUTPUT_TYPE_ROUNDS",
    "DEFAULT_TOPIC_FOCUS_INFER_THRESHOLD",
    "infer_auto_output_type",
    "stabilize_output_type",
]
