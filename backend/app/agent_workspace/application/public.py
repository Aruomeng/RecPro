"""Public use-case surface consumed by HTTP adapters."""

from backend.app.agent_workspace.runtime import (
    AgentWorkspaceBroker,
    WorkspaceCapacityError,
    WorkspaceConflictError,
    WorkspaceNotFoundError,
    agent_catalog,
)
from backend.app.agent_workspace.dispatcher import WorkspaceObservationCapacityError

__all__ = [
    "AgentWorkspaceBroker",
    "WorkspaceCapacityError",
    "WorkspaceConflictError",
    "WorkspaceNotFoundError",
    "WorkspaceObservationCapacityError",
    "agent_catalog",
]
