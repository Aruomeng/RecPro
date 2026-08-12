"""Immutable Agent registry and dispatch boundary."""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

from backend.app.shared_kernel.contracts.autonomy import (
    AgentAutonomyError,
    ROLE_PROFILES,
    assert_payload_decision,
    profile_for,
    validate_decision,
)
from backend.app.recommendation.agents.base import Agent
from backend.app.shared_kernel.contracts.agent import AgentMessage, AgentResult


class AgentUnavailableError(LookupError):
    """The orchestrator addressed an Agent that is not registered."""


class AgentProtocolError(ValueError):
    """An Agent returned a result outside the role/action protocol."""


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
            if name not in ROLE_PROFILES:
                raise AgentProtocolError(f"Agent {name} has no role profile")
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

    def profile(self, name: str):
        """Return the immutable role profile exposed to inspection tooling."""

        return profile_for(name)

    async def dispatch(self, message: AgentMessage) -> AgentResult[dict[str, object]]:
        try:
            result = await self.resolve(message.receiver).handle(message)
            if result.agent_name != message.receiver:
                raise AgentProtocolError("AgentResult.agent_name does not match receiver")
            if result.decision is None:
                raise AgentProtocolError("AgentResult must include a local autonomy decision")
            validate_decision(message.receiver, result.decision)
            assert_payload_decision(result.payload, result.decision)
            return result
        except AgentAutonomyError as exc:
            raise AgentProtocolError(str(exc)) from exc


__all__ = ["AgentProtocolError", "AgentRegistry", "AgentUnavailableError"]
