"""DeepSeek-backed, directive-only background planning adapter.

The adapter deliberately has no access to persistence, graph, vector or tool
ports.  It receives the already-sanitized Workspace context and returns raw
directive candidates for the application-layer validator to accept or reject.
Construction and invocation are separate so a future approved runtime can
inject a real provider without changing Workspace policy code.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Mapping, Protocol

from backend.app.agent_workspace.ports.planning import (
    BackgroundPlanningPort,
    BackgroundPlanningResult,
    SanitizedPlanningContext,
)
from backend.app.llm.ports.public import LLMResult


class BackgroundPlanningModelPort(Protocol):
    """The only model capability granted to ambient Workspace planning."""

    async def plan_workspace_background(self, context_json: str) -> LLMResult: ...


@dataclass(frozen=True, slots=True)
class DeepSeekBackgroundPlanner(BackgroundPlanningPort):
    """Adapt a capability-scoped DeepSeek provider to Workspace planning."""

    provider: BackgroundPlanningModelPort

    async def plan(self, context: SanitizedPlanningContext) -> BackgroundPlanningResult:
        context_json = json.dumps(
            {
                "mode": context.mode,
                "context_version": context.context_version,
                "trigger": context.trigger,
                "route": context.route,
                "query": context.query,
                "top_topics": list(context.top_topics),
                "source_statuses": dict(context.source_statuses),
                "external_context": list(context.external_context),
                "profile_summary": dict(context.profile_summary)
                if context.profile_summary is not None
                else None,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        if len(context_json) > 3000:
            raise ValueError("sanitized background context exceeds the model boundary")
        result = await self.provider.plan_workspace_background(context_json)
        directives = result.payload.get("directives")
        if not isinstance(directives, list) or len(directives) > 7:
            raise ValueError("background model response does not contain bounded directives")
        if any(not isinstance(item, Mapping) for item in directives):
            raise ValueError("background model response contains a non-object directive")
        confidence_values = [
            float(item["confidence"])
            for item in directives
            if isinstance(item.get("confidence"), (int, float))
            and not isinstance(item.get("confidence"), bool)
        ]
        return BackgroundPlanningResult(
            directives=tuple(dict(item) for item in directives),
            evidence_refs=("workspace:context", "prompt:workspace.background_plan"),
            confidence=max(confidence_values, default=0.0),
            provider=result.provider,
            model=result.model,
            model_requests=1,
        )


__all__ = ["BackgroundPlanningModelPort", "DeepSeekBackgroundPlanner"]
