"""Framework-independent Agent boundary for the G4 in-process orchestrator."""

from __future__ import annotations

from typing import Protocol

from backend.app.shared_kernel.contracts.agent import AgentMessage, AgentResult


class Agent(Protocol):
    """One addressable capability; Agents never call one another directly."""

    @property
    def name(self) -> str:
        ...

    @property
    def version(self) -> str:
        ...

    async def handle(self, message: AgentMessage) -> AgentResult[dict[str, object]]:
        """Handle one validated message and return a structured result."""


__all__ = ["Agent"]
