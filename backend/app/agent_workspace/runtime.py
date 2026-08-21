"""Bounded global Agent workspace and deterministic ambient coordination.

The workspace deliberately stays in memory.  It observes public kiosk events,
dispatches a small set of existing Agent roles through explicit handlers, and
emits allow-listed interaction directives.  It never calls an LLM or opens a
persistence connection.  An optional demo-only audit buffer can receive the
already-sanitised public facts; a separately gated worker owns persistence.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
import time
from typing import AsyncIterator, Callable, Mapping
from uuid import UUID, uuid4

from backend.app.agent_workspace.context import ContextProvider, default_external_context_providers
from backend.app.agent_workspace.audit import AgentWorkspaceAuditBuffer
from backend.app.shared_kernel.contracts.autonomy import ROLE_PROFILES


AGENT_NAMES = tuple(ROLE_PROFILES)
AGENT_STATES = frozenset(
    {"IDLE", "OBSERVING", "PLANNING", "WORKING", "WAITING_USER", "COMPLETED", "DEGRADED", "FAILED"}
)
OBSERVATION_TYPES = frozenset(
    {
        "SESSION_STARTED", "ROUTE_CHANGED", "QUERY_SUBMITTED", "GRAPH_NODE_SELECTED",
        "RESOURCE_OPENED", "RECOMMENDATION_STARTED", "RECOMMENDATION_COMPLETED",
        "FEEDBACK_RECORDED", "READINESS_CHANGED", "EXTERNAL_CONTEXT_UPDATED",
    }
)
DIRECTIVE_TYPES = frozenset(
    {
        "SUGGEST_TOPICS", "SET_PRIMARY_ENTRY", "PREFER_OUTPUT_TYPE",
        "SET_EXPLANATION_DENSITY", "SHOW_GUIDANCE", "SHOW_DEGRADED_NOTICE",
        "SUGGEST_NEXT_ACTION",
    }
)
DIRECTIVE_ACTIONS = frozenset({"ACCEPT", "DISMISS", "UNDO"})


class WorkspaceCapacityError(RuntimeError):
    pass


class WorkspaceNotFoundError(LookupError):
    pass


class WorkspaceConflictError(ValueError):
    pass


@dataclass(slots=True)
class _Workspace:
    workspace_id: UUID
    session_id: UUID
    user_id: int
    mode: str
    created_at: float
    last_active_at: float
    context_version: int = 1
    events: deque[dict[str, object]] = field(default_factory=lambda: deque(maxlen=512))
    subscribers: set[asyncio.Queue[dict[str, object]]] = field(default_factory=set)
    agents: dict[str, dict[str, object]] = field(default_factory=dict)
    directives: dict[str, dict[str, object]] = field(default_factory=dict)
    observation_keys: deque[str] = field(default_factory=lambda: deque(maxlen=512))
    observation_key_set: set[str] = field(default_factory=set)
    stability: dict[str, tuple[str, int]] = field(default_factory=dict)
    suppressed_until: dict[str, float] = field(default_factory=dict)
    last_auto_apply: dict[str, float] = field(default_factory=dict)
    current_route: str = "/"
    current_query: str = ""
    orchestrator_status: str = "OBSERVING"
    source_statuses: dict[str, str] = field(
        default_factory=lambda: {"mysql": "UNKNOWN", "neo4j": "UNKNOWN", "chroma": "UNKNOWN", "llm": "UNKNOWN"}
    )
    external_context: list[dict[str, object]] = field(default_factory=list)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None = None) -> str:
    return (value or _utc_now()).isoformat().replace("+00:00", "Z")


def _public_agent(name: str) -> dict[str, object]:
    profile = ROLE_PROFILES[name]
    return {
        "name": name,
        "role": profile.role,
        "goal": profile.goal,
        "state": "IDLE",
        "last_action": None,
        "target": None,
        "reason_code": None,
        "confidence": None,
        "duration_ms": None,
        "tools": list(profile.tools),
        "evidence_refs": [],
        "updated_at": _iso(),
    }


def agent_catalog() -> list[dict[str, object]]:
    return [
        {
            "name": profile.name,
            "role": profile.role,
            "goal": profile.goal,
            "observations": list(profile.observations),
            "tools": list(profile.tools),
            "allowed_actions": [item.value for item in profile.allowed_actions],
            "allowed_targets": list(profile.allowed_targets),
        }
        for profile in ROLE_PROFILES.values()
    ]


class MirroredProgressSink:
    """Publish to the task broker and the owning global workspace."""

    def __init__(self, primary: object, workspace: "AgentWorkspaceBroker", workspace_id: UUID, user_id: int) -> None:
        self._primary = primary
        self._workspace = workspace
        self._workspace_id = workspace_id
        self._user_id = user_id

    def publish(self, event_type: str, payload: dict[str, object]) -> None:
        self._primary.publish(event_type, payload)
        self._workspace.bridge_recommendation_event(
            self._workspace_id, user_id=self._user_id, event_type=event_type, payload=payload
        )


class AgentWorkspaceBroker:
    """Own workspaces, events, agent state and bounded UI policies."""

    def __init__(
        self,
        *,
        max_workspaces: int = 32,
        retention_seconds: float = 600.0,
        context_providers: tuple[ContextProvider, ...] | None = None,
        audit_buffer: AgentWorkspaceAuditBuffer | None = None,
        workspace_id_factory: Callable[[], UUID] = uuid4,
        directive_id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._max_workspaces = max_workspaces
        self._retention_seconds = retention_seconds
        self._context_providers = context_providers or default_external_context_providers()
        self._audit_buffer = audit_buffer
        self._workspace_id_factory = workspace_id_factory
        self._directive_id_factory = directive_id_factory
        self._workspaces: dict[UUID, _Workspace] = {}
        self._by_session: dict[tuple[UUID, int, str], UUID] = {}

    def create(self, *, session_id: UUID, user_id: int, mode: str) -> tuple[dict[str, object], bool]:
        if mode not in {"guest", "demo"}:
            raise ValueError("workspace mode must be guest or demo")
        self._prune()
        key = (session_id, user_id, mode)
        existing_id = self._by_session.get(key)
        if existing_id is not None and existing_id in self._workspaces:
            return self.snapshot(existing_id, user_id=user_id), True
        if len(self._workspaces) >= self._max_workspaces:
            raise WorkspaceCapacityError("agent workspace capacity reached")
        now = time.monotonic()
        workspace = _Workspace(self._workspace_id_factory(), session_id, user_id, mode, now, now)
        workspace.agents = {name: _public_agent(name) for name in AGENT_NAMES}
        workspace.external_context = self._read_external_context()
        self._workspaces[workspace.workspace_id] = workspace
        self._by_session[key] = workspace.workspace_id
        self._publish(workspace, "WORKSPACE_CREATED", {"mode": mode, "status": "OBSERVING"})
        self.observe(
            workspace.workspace_id,
            user_id=user_id,
            event_type="SESSION_STARTED",
            idempotency_key=f"session:{session_id}",
            payload={"mode": mode},
        )
        return self.snapshot(workspace.workspace_id, user_id=user_id), False

    def snapshot(self, workspace_id: UUID, *, user_id: int) -> dict[str, object]:
        workspace = self._visible(workspace_id, user_id)
        return {
            "schema_version": "agent-workspace-v1",
            "workspace_id": str(workspace.workspace_id),
            "session_id": str(workspace.session_id),
            "mode": workspace.mode,
            "context_version": workspace.context_version,
            "orchestrator": {
                "name": "RecommendationOrchestrator",
                "role": "全局协作编排器",
                "state": workspace.orchestrator_status,
                "current_route": workspace.current_route,
            },
            "agents": list(workspace.agents.values()),
            "directives": [value for value in workspace.directives.values() if value.get("status") in {"PROPOSED", "AUTO_APPLIED", "ACCEPTED"}],
            "recent_events": list(workspace.events)[-40:],
            "sources": self._sources(workspace),
            "context_summary": {"route": workspace.current_route, "query": workspace.current_query, "external": workspace.external_context},
        }

    def observe(
        self,
        workspace_id: UUID,
        *,
        user_id: int,
        event_type: str,
        idempotency_key: str,
        payload: Mapping[str, object] | None = None,
    ) -> tuple[dict[str, object], bool]:
        workspace = self._visible(workspace_id, user_id)
        if event_type not in OBSERVATION_TYPES:
            raise ValueError("observation type is not allowed")
        if not idempotency_key.strip() or len(idempotency_key) > 255:
            raise ValueError("observation idempotency key is invalid")
        if idempotency_key in workspace.observation_key_set:
            return self.snapshot(workspace_id, user_id=user_id), True
        self._remember_key(workspace, idempotency_key)
        clean = self._sanitize_payload(payload or {})
        workspace.context_version += 1
        workspace.last_active_at = time.monotonic()
        if event_type == "ROUTE_CHANGED" and isinstance(clean.get("route"), str):
            workspace.current_route = str(clean["route"])
        if event_type == "QUERY_SUBMITTED" and isinstance(clean.get("query"), str):
            workspace.current_query = str(clean["query"])
        if event_type == "READINESS_CHANGED":
            self._apply_readiness(workspace, clean)
        self._publish(workspace, "OBSERVATION_ACCEPTED", {"observation_type": event_type, "source": "kiosk", "context_version": workspace.context_version})
        self._coordinate(workspace, event_type, clean)
        return self.snapshot(workspace_id, user_id=user_id), False

    def directive_action(self, workspace_id: UUID, *, user_id: int, directive_id: UUID, action: str) -> dict[str, object]:
        workspace = self._visible(workspace_id, user_id)
        if action not in DIRECTIVE_ACTIONS:
            raise ValueError("directive action is not allowed")
        directive = workspace.directives.get(str(directive_id))
        if directive is None:
            raise WorkspaceNotFoundError("directive not found")
        directive["status"] = {"ACCEPT": "ACCEPTED", "DISMISS": "DISMISSED", "UNDO": "UNDONE"}[action]
        directive["updated_at"] = _iso()
        if action in {"DISMISS", "UNDO"}:
            workspace.suppressed_until[str(directive["type"])] = time.monotonic() + 600.0
        self._publish(workspace, "DIRECTIVE_ACTIONED", {"directive_id": str(directive_id), "directive_type": directive["type"], "action": action})
        self._capture_directive(workspace, directive)
        return dict(directive)

    def mirror_sink(self, primary: object, workspace_id: UUID, *, user_id: int) -> MirroredProgressSink:
        self._visible(workspace_id, user_id)
        return MirroredProgressSink(primary, self, workspace_id, user_id)

    def bridge_recommendation_event(self, workspace_id: UUID, *, user_id: int, event_type: str, payload: Mapping[str, object]) -> None:
        workspace = self._visible(workspace_id, user_id)
        clean = self._sanitize_payload(payload)
        if event_type == "AGENT_STARTED":
            name = str(clean.get("agent_name", ""))
            if name in workspace.agents:
                self._set_agent(workspace, name, "WORKING", action=str(clean.get("message_type", "DISPATCH")), target="RecommendationOrchestrator", reason="RECOMMENDATION_DISPATCH")
        elif event_type == "AGENT_COMPLETED":
            name = str(clean.get("agent_name", ""))
            if name in workspace.agents:
                state = "FAILED" if clean.get("outcome") == "FAILED" else "DEGRADED" if clean.get("fallback_used") else "COMPLETED"
                self._set_agent(
                    workspace, name, state,
                    action=str(clean.get("action", "RETURN_RESULT")),
                    target=str(clean.get("target", "RecommendationOrchestrator")),
                    reason=str(clean.get("reason_code", "RECOMMENDATION_RESULT")),
                    confidence=clean.get("confidence"), duration_ms=clean.get("duration_ms"),
                    evidence_refs=clean.get("evidence_refs"),
                )
        elif event_type == "STATE_CHANGED":
            workspace.orchestrator_status = "WORKING"
        self._publish(workspace, "RECOMMENDATION_EVENT", {"recommendation_event_type": event_type, **clean})

    def bridge_task_terminal(self, workspace_id: UUID, *, user_id: int, status: str, task_id: UUID, trace_id: UUID | None = None) -> None:
        workspace = self._visible(workspace_id, user_id)
        workspace.orchestrator_status = "FAILED" if status == "FAILED" else "COMPLETED"
        self._publish(workspace, "RECOMMENDATION_COMPLETED", {"status": status, "task_id": str(task_id), **({"trace_id": str(trace_id)} if trace_id else {})})
        self._dispatch_policy(workspace, "RECOMMENDATION_COMPLETED", {"status": status})

    def bridge_feedback_action(self, workspace_id: UUID, *, user_id: int, action: Mapping[str, object]) -> None:
        workspace = self._visible(workspace_id, user_id)
        clean = self._sanitize_payload(action)
        self._dispatch(workspace, "FeedbackLearningAgent", action=str(clean.get("action", "PROPOSE_PROFILE_DELTA")), target=str(clean.get("target", "UserProfileAgent")), reason=str(clean.get("reason_code", "FEEDBACK_RECORDED")), confidence=clean.get("confidence"), evidence_refs=clean.get("evidence_refs"))
        self._dispatch_policy(workspace, "FEEDBACK_RECORDED", clean)

    async def events(self, workspace_id: UUID, *, user_id: int, after_sequence: int = 0) -> AsyncIterator[dict[str, object] | None]:
        workspace = self._visible(workspace_id, user_id)
        queue: asyncio.Queue[dict[str, object]] = asyncio.Queue(maxsize=512)
        for event in workspace.events:
            if int(event["sequence"]) > after_sequence:
                queue.put_nowait(event)
        workspace.subscribers.add(queue)
        try:
            while True:
                try:
                    yield await asyncio.wait_for(queue.get(), timeout=15.0)
                except TimeoutError:
                    yield None
        finally:
            workspace.subscribers.discard(queue)

    def _coordinate(self, workspace: _Workspace, event_type: str, payload: Mapping[str, object]) -> None:
        if event_type == "QUERY_SUBMITTED":
            self._dispatch(workspace, "IntentUnderstandingAgent", action="RETURN_RESULT", target="RecommendationOrchestrator", reason="QUERY_CONTEXT_NORMALIZED", confidence=0.86, evidence_refs=("session:query",))
            return
        if event_type in {"GRAPH_NODE_SELECTED", "RESOURCE_OPENED"}:
            self._dispatch(workspace, "ResourceSemanticAgent", action="PROBE_RESOURCES", target="RecommendationPolicyAgent", reason="SEMANTIC_CONTEXT_CHANGED", confidence=0.84, evidence_refs=("neo4j:public-subgraph" if event_type == "GRAPH_NODE_SELECTED" else "mysql:resource-detail",))
            self._dispatch_policy(workspace, event_type, payload)
            return
        if event_type == "FEEDBACK_RECORDED":
            self._dispatch(workspace, "FeedbackLearningAgent", action="PROPOSE_PROFILE_DELTA", target="UserProfileAgent", reason="SESSION_FEEDBACK_OBSERVED", confidence=0.88, evidence_refs=("session:feedback",))
            self._dispatch_policy(workspace, event_type, payload)
            return
        if event_type == "SESSION_STARTED" and workspace.mode == "demo":
            self._dispatch(workspace, "UserProfileAgent", action="READ_PROFILE", target="RecommendationOrchestrator", reason="DEMO_PROFILE_CONTEXT", confidence=0.80, evidence_refs=("profile:demo-1001",))
        if event_type in {"SESSION_STARTED", "ROUTE_CHANGED", "READINESS_CHANGED", "EXTERNAL_CONTEXT_UPDATED", "RECOMMENDATION_COMPLETED"}:
            self._dispatch_policy(workspace, event_type, payload)

    def _dispatch_policy(self, workspace: _Workspace, event_type: str, payload: Mapping[str, object]) -> None:
        self._dispatch(workspace, "RecommendationPolicyAgent", action="PLAN_RECALL", target="User", reason=f"{event_type}_POLICY_EVALUATED", confidence=0.82, evidence_refs=("workspace:context", "external:demo-context"))
        if event_type == "SESSION_STARTED":
            density = "DETAILED" if workspace.mode == "guest" else "BALANCED"
            self._propose(workspace, "SHOW_GUIDANCE", "global", "AUTO_APPLY", {"density": density, "message": "我会根据你正在浏览的内容提供下一步建议。"}, "NEW_SESSION_GUIDANCE", 0.82, ("session:mode",), reversible=True)
            self._propose(workspace, "SET_EXPLANATION_DENSITY", "global", "AUTO_APPLY", {"density": density}, "IDENTITY_MODE_ADAPTATION", 0.84, ("session:mode",), reversible=True)
            self._propose(workspace, "SET_PRIMARY_ENTRY", "home", "AUTO_APPLY", {"route": "/recommend", "label": "从研究主题开始"}, "ACADEMIC_CONTEXT_ACTIVE", 0.81, ("external:academic-calendar",), reversible=True)
            self._propose(workspace, "SUGGEST_TOPICS", "home", "SUGGESTION", {"topics": ["多智能体", "推荐系统", "知识图谱", "智慧图书馆"]}, "LIBRARY_RESEARCH_CONTEXT", 0.86, ("external:academic-calendar", "mysql:popular-topics"), reversible=True)
        elif event_type == "ROUTE_CHANGED":
            density = "DETAILED" if workspace.mode == "guest" else "BALANCED"
            self._propose(workspace, "SHOW_GUIDANCE", "global", "AUTO_APPLY", {"density": density, "message": "我会根据你正在浏览的内容提供下一步建议。"}, "NEW_SESSION_GUIDANCE", 0.82, ("session:mode",), reversible=True)
            self._propose(workspace, "SET_EXPLANATION_DENSITY", "global", "AUTO_APPLY", {"density": density}, "IDENTITY_MODE_ADAPTATION", 0.84, ("session:mode",), reversible=True)
            self._propose(workspace, "SET_PRIMARY_ENTRY", "home", "AUTO_APPLY", {"route": "/recommend", "label": "从研究主题开始"}, "ACADEMIC_CONTEXT_ACTIVE", 0.81, ("external:academic-calendar",), reversible=True)
            preferred = "READING_PATH" if workspace.current_route == "/path" else "TOPIC_RESOURCES"
            self._propose(workspace, "PREFER_OUTPUT_TYPE", workspace.current_route, "SUGGESTION", {"output_type": preferred}, "ROUTE_INTENT_HINT", 0.78, ("session:route",), reversible=True)
        elif event_type in {"GRAPH_NODE_SELECTED", "RESOURCE_OPENED"}:
            label = str(payload.get("label") or payload.get("title") or "当前知识实体")[:80]
            self._propose(workspace, "SUGGEST_NEXT_ACTION", workspace.current_route, "SUGGESTION", {"label": f"围绕“{label}”生成关联书单", "action": "OPEN_RECOMMEND", "query": label}, "SEMANTIC_CONTEXT_AVAILABLE", 0.84, ("workspace:selected-entity",), reversible=True)
        elif event_type == "READINESS_CHANGED":
            degraded = [str(item) for item in payload.get("degraded", [])] if isinstance(payload.get("degraded"), list) else []
            if degraded:
                self._propose(workspace, "SHOW_DEGRADED_NOTICE", "global", "NOTICE", {"components": degraded, "message": "部分检索通道暂不可用，系统将保留可用通道继续工作。"}, "RUNTIME_CHANNEL_DEGRADED", 1.0, tuple(f"readiness:{item}" for item in degraded), reversible=False)
        elif event_type == "RECOMMENDATION_COMPLETED":
            self._propose(workspace, "SUGGEST_NEXT_ACTION", "recommend", "SUGGESTION", {"label": "在知识图谱中查看结果关联", "action": "OPEN_GRAPH", "query": workspace.current_query}, "RECOMMENDATION_CONTEXT_READY", 0.81, ("workspace:recommendation-result",), reversible=True)
        elif event_type == "FEEDBACK_RECORDED":
            self._propose(workspace, "SUGGEST_NEXT_ACTION", "global", "SUGGESTION", {"label": "依据刚才的反馈重新推荐", "action": "RECOMMEND_AGAIN"}, "FEEDBACK_POLICY_REFRESH", 0.88, ("workspace:feedback",), reversible=True)

    def _dispatch(self, workspace: _Workspace, name: str, *, action: str, target: str, reason: str, confidence: object = 0.8, duration_ms: object = 0, evidence_refs: object = ()) -> None:
        started = time.perf_counter()
        self._set_agent(workspace, name, "WORKING", action=action, target=target, reason=reason)
        self._publish(workspace, "AGENT_STARTED", {"agent_name": name, "action": action, "target": target, "reason_code": reason})
        measured = max(int((time.perf_counter() - started) * 1000), int(duration_ms) if isinstance(duration_ms, int) else 0)
        refs = tuple(str(item)[:120] for item in evidence_refs) if isinstance(evidence_refs, (list, tuple)) else ()
        numeric = float(confidence) if isinstance(confidence, (int, float)) and not isinstance(confidence, bool) else 0.8
        self._set_agent(workspace, name, "COMPLETED", action=action, target=target, reason=reason, confidence=numeric, duration_ms=measured, evidence_refs=refs)
        self._publish(workspace, "AGENT_COMPLETED", {"agent_name": name, "action": action, "target": target, "reason_code": reason, "confidence": numeric, "duration_ms": measured, "evidence_refs": list(refs), "outcome": "SUCCESS"})

    def _propose(self, workspace: _Workspace, directive_type: str, scope: str, behavior: str, payload: Mapping[str, object], reason: str, confidence: float, evidence_refs: tuple[str, ...], *, reversible: bool) -> None:
        if directive_type not in DIRECTIVE_TYPES or behavior not in {"AUTO_APPLY", "SUGGESTION", "NOTICE"}:
            raise ValueError("interaction directive is outside the allowlist")
        now = time.monotonic()
        if workspace.suppressed_until.get(directive_type, 0) > now:
            return
        signature = sha256(json.dumps([directive_type, scope, payload], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        old_signature, count = workspace.stability.get(directive_type, ("", 0))
        stable_count = count + 1 if old_signature == signature else 1
        workspace.stability[directive_type] = (signature, stable_count)
        status = "PROPOSED"
        if behavior == "AUTO_APPLY" and confidence >= 0.75 and stable_count >= 2 and now - workspace.last_auto_apply.get(directive_type, -1000) >= 30:
            status = "AUTO_APPLIED"
            workspace.last_auto_apply[directive_type] = now
        directive_id = self._directive_id_factory()
        directive = {
            "directive_id": str(directive_id), "directive_version": 1, "type": directive_type,
            "scope": scope[:80], "behavior": behavior, "payload": self._sanitize_payload(payload),
            "reason_codes": [reason], "evidence_refs": list(evidence_refs), "confidence": confidence,
            "created_at": _iso(), "expires_at": _iso(_utc_now() + timedelta(minutes=10)),
            "reversible": reversible, "status": status,
        }
        workspace.directives[str(directive_id)] = directive
        self._publish(workspace, "DIRECTIVE_PROPOSED", {"directive": directive})
        self._capture_directive(workspace, directive)

    def _set_agent(self, workspace: _Workspace, name: str, state: str, *, action: str, target: str, reason: str, confidence: object = None, duration_ms: object = None, evidence_refs: object = ()) -> None:
        if name not in workspace.agents or state not in AGENT_STATES:
            return
        agent = workspace.agents[name]
        agent.update({
            "state": state, "last_action": action[:80], "target": target[:80], "reason_code": reason[:120],
            "confidence": confidence if isinstance(confidence, (int, float)) else None,
            "duration_ms": duration_ms if isinstance(duration_ms, int) else None,
            "evidence_refs": [str(item)[:120] for item in evidence_refs] if isinstance(evidence_refs, (list, tuple)) else [],
            "updated_at": _iso(),
        })
        workspace.orchestrator_status = "WORKING" if state == "WORKING" else "OBSERVING"

    def _publish(self, workspace: _Workspace, event_type: str, payload: Mapping[str, object]) -> dict[str, object]:
        event = {
            "schema_version": "agent-workspace-event-v1",
            "sequence": int(workspace.events[-1]["sequence"]) + 1 if workspace.events else 1,
            "event_type": event_type,
            "workspace_id": str(workspace.workspace_id),
            "context_version": workspace.context_version,
            "occurred_at": _iso(),
            **self._sanitize_payload(payload),
        }
        workspace.events.append(event)
        workspace.last_active_at = time.monotonic()
        if self._audit_buffer is not None:
            self._audit_buffer.capture_event(
                mode=workspace.mode,
                session_id=workspace.session_id,
                user_id=workspace.user_id,
                event=event,
                replayed=bool(event.get("replayed", False)),
            )
        for queue in tuple(workspace.subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                workspace.subscribers.discard(queue)
        return event

    def _capture_directive(self, workspace: _Workspace, directive: Mapping[str, object]) -> None:
        if self._audit_buffer is None:
            return
        self._audit_buffer.capture_directive(
            mode=workspace.mode,
            workspace_id=workspace.workspace_id,
            session_id=workspace.session_id,
            user_id=workspace.user_id,
            directive=directive,
        )

    @staticmethod
    def _sanitize_payload(payload: Mapping[str, object]) -> dict[str, object]:
        blocked = {"prompt", "raw_prompt", "model_output", "sql", "cypher", "password", "secret", "api_key", "profile"}

        def public_value(value: object, depth: int = 0) -> object:
            if value is None or isinstance(value, (bool, int, float)):
                return value
            if isinstance(value, str):
                return value[:500]
            if isinstance(value, (list, tuple)):
                return [public_value(item, depth + 1) for item in value[:20]]
            if isinstance(value, Mapping) and depth < 3:
                return {
                    str(key)[:80]: public_value(item, depth + 1)
                    for key, item in list(value.items())[:24]
                    if str(key).lower() not in blocked
                }
            return str(value)[:160]

        clean = {
            str(key)[:80]: public_value(value)
            for key, value in list(payload.items())[:24]
            if str(key).lower() not in blocked
        }
        encoded = json.dumps(clean, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode()) > 8192:
            raise ValueError("public workspace payload is too large")
        return clean

    @staticmethod
    def _apply_readiness(workspace: _Workspace, payload: Mapping[str, object]) -> None:
        degraded = (
            {str(item).lower() for item in payload.get("degraded", []) if isinstance(item, str)}
            if isinstance(payload.get("degraded"), list)
            else set()
        )
        aliases = {"mysql": "mysql", "neo4j": "neo4j", "chroma": "chroma", "vector": "chroma", "llm": "llm"}
        for source_id in workspace.source_statuses:
            workspace.source_statuses[source_id] = "UP"
        for component in degraded:
            source_id = aliases.get(component)
            if source_id is not None:
                workspace.source_statuses[source_id] = "DEGRADED"

        affected_agents = {
            "mysql": ("ResourceSemanticAgent", "CandidateRecallAgent"),
            "neo4j": ("ResourceSemanticAgent", "CandidateRecallAgent"),
            "chroma": ("CandidateRecallAgent",),
            "llm": ("IntentUnderstandingAgent", "RankingAgent", "ExplanationAgent"),
        }
        for source_id, names in affected_agents.items():
            is_degraded = workspace.source_statuses[source_id] == "DEGRADED"
            for name in names:
                agent = workspace.agents[name]
                if is_degraded:
                    agent.update({
                        "state": "DEGRADED",
                        "last_action": "OBSERVE_READINESS",
                        "target": source_id,
                        "reason_code": f"{source_id.upper()}_DEGRADED",
                        "confidence": 1.0,
                        "duration_ms": 0,
                        "evidence_refs": [f"readiness:{source_id}"],
                        "updated_at": _iso(),
                    })
                elif (
                    agent.get("state") == "DEGRADED"
                    and agent.get("last_action") == "OBSERVE_READINESS"
                    and agent.get("target") == source_id
                ):
                    agent.update({
                        "state": "IDLE",
                        "last_action": "READINESS_RECOVERED",
                        "reason_code": f"{source_id.upper()}_RECOVERED",
                        "confidence": 1.0,
                        "updated_at": _iso(),
                    })

    def _read_external_context(self) -> list[dict[str, object]]:
        now = _utc_now()
        observations: list[dict[str, object]] = []
        for provider in self._context_providers:
            try:
                observation = provider.read(now=now)
                observations.append({
                    "source_id": observation.source_id,
                    "kind": observation.kind,
                    "label": observation.label,
                    "status": observation.status,
                    "observed_at": _iso(observation.observed_at),
                    "expires_at": _iso(observation.expires_at),
                    "values": self._sanitize_payload(observation.values),
                })
            except Exception:
                observations.append({
                    "source_id": f"external-provider-{len(observations) + 1}",
                    "kind": "EXTERNAL_DEMO",
                    "label": "演示外部情境",
                    "status": "DEGRADED",
                    "observed_at": _iso(now),
                    "expires_at": _iso(now + timedelta(minutes=5)),
                    "values": {"reason_code": "EXTERNAL_CONTEXT_UNAVAILABLE"},
                })
        return observations

    @staticmethod
    def _sources(workspace: _Workspace) -> list[dict[str, object]]:
        now = _utc_now()
        expires = now + timedelta(minutes=5)
        return [
            {"source_id": "internal-session", "kind": "INTERNAL", "label": "当前会话", "status": "UP", "observed_at": _iso(now), "expires_at": _iso(expires)},
            {"source_id": "mysql", "kind": "INTERNAL", "label": "MySQL 馆藏", "status": workspace.source_statuses["mysql"], "observed_at": _iso(now), "expires_at": _iso(expires)},
            {"source_id": "neo4j", "kind": "INTERNAL", "label": "Neo4j 知识图谱", "status": workspace.source_statuses["neo4j"], "observed_at": _iso(now), "expires_at": _iso(expires)},
            {"source_id": "chroma", "kind": "INTERNAL", "label": "Chroma 向量召回", "status": workspace.source_statuses["chroma"], "observed_at": _iso(now), "expires_at": _iso(expires)},
            {"source_id": "llm", "kind": "INTERNAL", "label": "DeepSeek LLM", "status": workspace.source_statuses["llm"], "observed_at": _iso(now), "expires_at": _iso(expires)},
        ] + [{key: value for key, value in item.items() if key != "values"} for item in workspace.external_context]

    def _visible(self, workspace_id: UUID, user_id: int) -> _Workspace:
        self._prune()
        workspace = self._workspaces.get(workspace_id)
        if workspace is None or workspace.user_id != user_id:
            raise WorkspaceNotFoundError("agent workspace was not found")
        workspace.last_active_at = time.monotonic()
        return workspace

    @staticmethod
    def _remember_key(workspace: _Workspace, key: str) -> None:
        if len(workspace.observation_keys) == workspace.observation_keys.maxlen:
            removed = workspace.observation_keys.popleft()
            workspace.observation_key_set.discard(removed)
        workspace.observation_keys.append(key)
        workspace.observation_key_set.add(key)

    def _prune(self) -> None:
        now = time.monotonic()
        stale = [wid for wid, workspace in self._workspaces.items() if now - workspace.last_active_at > self._retention_seconds]
        for wid in stale:
            workspace = self._workspaces.pop(wid)
            self._by_session.pop((workspace.session_id, workspace.user_id, workspace.mode), None)


__all__ = [
    "AGENT_NAMES", "DIRECTIVE_ACTIONS", "DIRECTIVE_TYPES", "OBSERVATION_TYPES",
    "AgentWorkspaceBroker", "WorkspaceCapacityError", "WorkspaceConflictError",
    "WorkspaceNotFoundError", "agent_catalog",
]
