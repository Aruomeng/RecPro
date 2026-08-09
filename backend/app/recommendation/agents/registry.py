"""Immutable Agent registry and dispatch boundary."""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

from backend.app.recommendation.agents.base import Agent
from backend.app.shared_kernel.contracts.agent import AgentMessage, AgentResult


class AgentUnavailableError(LookupError):
    """The orchestrator addressed an Agent that is not registered."""


class AgentRegistry:
    """Resolve and dispatch Agents without exposing implementation references."""

    def __init__(self, agents: Mapping[str, Agent]) -> None:
        if not agents:
            raise ValueError("at least one Agent must be registered")
        normalized: dict[str, Agent] = {}
        for name, agent in agents.items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError("Agent registry names must be non-blank")
            if name != agent.name:
                raise ValueError("registry key must equal Agent.name")
            if name in normalized:
                raise ValueError(f"duplicate Agent name: {name}")
            normalized[name] = agent
        self._agents = MappingProxyType(normalized)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._agents))

    def resolve(self, name: str) -> Agent:
        try:
            return self._agents[name]
        except KeyError as exc:
            raise AgentUnavailableError(name) from exc

    async def dispatch(self, message: AgentMessage) -> AgentResult[dict[str, object]]:
        return await self.resolve(message.receiver).handle(message)


__all__ = ["AgentRegistry", "AgentUnavailableError"]
