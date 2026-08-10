"""Framework-independent observability domain types."""

from .health import (
    ComponentReadiness,
    ComponentStatus,
    ReadinessAssessment,
    ServiceReadinessStatus,
)
from .transition import StateTransition, transition_uuid

__all__ = [
    "ComponentReadiness",
    "ComponentStatus",
    "ReadinessAssessment",
    "ServiceReadinessStatus",
    "StateTransition",
    "transition_uuid",
]
