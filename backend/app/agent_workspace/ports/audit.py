"""Append-only persistence contract for public Workspace audit facts."""

from __future__ import annotations

from typing import Protocol

from backend.app.agent_workspace.audit import AuditFact


class AgentWorkspaceAuditPort(Protocol):
    async def append(self, connection: object, fact: AuditFact) -> None: ...


__all__ = ["AgentWorkspaceAuditPort"]
