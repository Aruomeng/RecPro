"""Session-scoped, in-memory Agent workspace for the research kiosk."""

from .context import ContextObservation, ContextProvider, LocalDemoExternalContextProvider
from .audit import AgentWorkspaceAuditBuffer, AuditCapacityError
from .dispatcher import WorkspaceObservationCapacityError
from .application.background_planning import (
    BackgroundPlanningCoordinator,
    DirectiveValidationError,
    DirectiveValidator,
    FixtureBackgroundPlanner,
    InMemoryPlanningBudget,
    PlanningBudgetPolicy,
    PlanningContextSanitizer,
)
from .handlers import ExplorationWorkspaceReadTools
from .topic_graph import SessionTopicGraph
from .runtime import (
    AGENT_NAMES,
    AgentWorkspaceBroker,
    WorkspaceCapacityError,
    WorkspaceConflictError,
    WorkspaceNotFoundError,
)

__all__ = [
    "AGENT_NAMES",
    "AgentWorkspaceBroker",
    "WorkspaceCapacityError",
    "WorkspaceConflictError",
    "WorkspaceNotFoundError",
    "ContextObservation",
    "ContextProvider",
    "LocalDemoExternalContextProvider",
    "AgentWorkspaceAuditBuffer",
    "AuditCapacityError",
    "ExplorationWorkspaceReadTools",
    "SessionTopicGraph",
    "WorkspaceObservationCapacityError",
    "BackgroundPlanningCoordinator",
    "DirectiveValidationError",
    "DirectiveValidator",
    "FixtureBackgroundPlanner",
    "InMemoryPlanningBudget",
    "PlanningBudgetPolicy",
    "PlanningContextSanitizer",
]
