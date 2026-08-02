"""Framework-independent observability domain types."""

from .health import (
    ComponentReadiness,
    ComponentStatus,
    ReadinessAssessment,
    ServiceReadinessStatus,
)

__all__ = [
    "ComponentReadiness",
    "ComponentStatus",
    "ReadinessAssessment",
    "ServiceReadinessStatus",
]
