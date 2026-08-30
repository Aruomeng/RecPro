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
import inspect
import json
import time
from typing import AsyncIterator, Callable, Mapping
from uuid import UUID, uuid4

from backend.app.agent_workspace.context import ContextProvider, default_external_context_providers
from backend.app.agent_workspace.audit import AgentWorkspaceAuditBuffer
from backend.app.agent_workspace.dispatcher import (
    WorkspaceObservationCapacityError,
    WorkspaceObservationDispatcher,
)
from backend.app.agent_workspace.handlers import default_workspace_handlers
from backend.app.agent_workspace.ports.handlers import (
    WorkspaceAgentHandler,
    WorkspaceAgentResult,
    WorkspaceHandlerContext,
    WorkspaceObservation,
    WorkspaceProfileReadPort,
    WorkspaceReadToolPort,
)
from backend.app.agent_workspace.application.background_planning import BackgroundPlanningCoordinator
from backend.app.agent_workspace.ports.planning import (
    BACKGROUND_PLANNING_TRIGGERS,
    BackgroundPlanningOutcome,
    PlanningContext,
    SanitizedPlanningContext,
)
from backend.app.agent_workspace.topic_graph import SessionTopicGraph
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
    replayed_task_ids: set[str] = field(default_factory=set)
    personalization_enabled: bool = False
    topic_graph: SessionTopicGraph = field(default_factory=SessionTopicGraph)
    observation_fingerprints: dict[str, str] = field(default_factory=dict)
    last_processed_context_version: int = 0
    current_observation: dict[str, object] | None = None
    device_id: str = ""
    background_planning: dict[str, object] | None = None


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
        handlers: tuple[WorkspaceAgentHandler, ...] | None = None,
        read_tools: WorkspaceReadToolPort | None = None,
        profile_reader: WorkspaceProfileReadPort | None = None,
        background_planner: BackgroundPlanningCoordinator | None = None,
        max_concurrent_observations: int = 16,
        max_pending_observations: int = 64,
        workspace_id_factory: Callable[[], UUID] = uuid4,
        directive_id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._max_workspaces = max_workspaces
        self._retention_seconds = retention_seconds
        self._context_providers = context_providers or default_external_context_providers()
        self._audit_buffer = audit_buffer
        self._handlers = handlers or default_workspace_handlers(
            read_tools=read_tools,
            profile_reader=profile_reader,
        )
        self._profile_reader = profile_reader
        self._background_planner = background_planner
        self._max_concurrent_observations = max_concurrent_observations
        self._max_pending_observations = max_pending_observations
        self._dispatcher: WorkspaceObservationDispatcher | None = None
        self._workspace_id_factory = workspace_id_factory
        self._directive_id_factory = directive_id_factory
        self._workspaces: dict[UUID, _Workspace] = {}
        self._by_session: dict[tuple[UUID, int, str], UUID] = {}
        self._closed = False

    async def close(self) -> None:
        """Drain accepted observations and release an injected profile reader."""

        if self._closed:
            return
        self._closed = True
        await self.wait_for_idle()
        close = getattr(self._profile_reader, "close", None)
        if not callable(close):
            return
        result = close()
        if inspect.isawaitable(result):
            await result

    def create(
        self,
        *,
        session_id: UUID,
        user_id: int,
        mode: str,
        personalization_enabled: bool = False,
        device_id: str | None = None,
    ) -> tuple[dict[str, object], bool]:
        if mode not in {"guest", "demo", "authenticated"}:
            raise ValueError("workspace mode must be guest, demo, or authenticated")
        self._prune()
        key = (session_id, user_id, mode)
        existing_id = self._by_session.get(key)
        if existing_id is not None and existing_id in self._workspaces:
            return self.snapshot(existing_id, user_id=user_id), True
        if len(self._workspaces) >= self._max_workspaces:
            raise WorkspaceCapacityError("agent workspace capacity reached")
        now = time.monotonic()
        workspace = _Workspace(
            self._workspace_id_factory(), session_id, user_id, mode, now, now,
            personalization_enabled=personalization_enabled,
            device_id=(device_id or f"session:{session_id}")[:128],
        )
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
        self._expire_directives(workspace)
        return {
            "schema_version": "agent-workspace-v2",
            "workspace_id": str(workspace.workspace_id),
            "session_id": str(workspace.session_id),
            "mode": workspace.mode,
            "context_version": workspace.context_version,
            "orchestrator": {
                "name": "RecommendationOrchestrator",
                "role": "全局协作编排器",
                "state": workspace.orchestrator_status,
                "current_route": workspace.current_route,
                "current_observation": workspace.current_observation,
            },
            "agents": list(workspace.agents.values()),
            "directives": [value for value in workspace.directives.values() if value.get("status") in {"PROPOSED", "AUTO_APPLIED", "ACCEPTED"}],
            "recent_events": list(workspace.events)[-40:],
            "sources": self._sources(workspace),
            "context_summary": {
                "route": workspace.current_route,
                "query": workspace.current_query,
                "external": workspace.external_context,
                "background_planning": workspace.background_planning,
            },
            "session_topic_graph": workspace.topic_graph.snapshot(),
        }

    def observe(
        self,
        workspace_id: UUID,
        *,
        user_id: int,
        event_type: str,
        idempotency_key: str,
        payload: Mapping[str, object] | None = None,
        personalization_enabled: bool | None = None,
    ) -> tuple[dict[str, object], bool]:
        workspace = self._visible(workspace_id, user_id)
        if event_type not in OBSERVATION_TYPES:
            raise ValueError("observation type is not allowed")
        if not idempotency_key.strip() or len(idempotency_key) > 255:
            raise ValueError("observation idempotency key is invalid")
        if idempotency_key in workspace.observation_key_set:
            return self.snapshot(workspace_id, user_id=user_id), True
        clean = self._sanitize_payload(payload or {})
        if personalization_enabled is not None:
            # The HTTP adapter derives this flag from the verified principal.
            # Formal accounts require the consent-derived permission; an
            # explicitly enabled research-demo workspace may use its synthetic
            # profile, while guests can never opt into profile reads through a
            # payload.
            workspace.personalization_enabled = (
                bool(personalization_enabled)
                if workspace.mode in {"authenticated", "demo"}
                else False
            )
        coalesced_fingerprint: str | None = None
        if event_type in {"ROUTE_CHANGED", "READINESS_CHANGED", "RESOURCE_OPENED"}:
            coalesced_fingerprint = sha256(
                json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            if workspace.observation_fingerprints.get(event_type) == coalesced_fingerprint:
                self._remember_key(workspace, idempotency_key)
                return self.snapshot(workspace_id, user_id=user_id), True
        dispatcher = self._runtime_dispatcher()
        if dispatcher is not None and dispatcher.pending_count >= self._max_pending_observations:
            raise WorkspaceObservationCapacityError("workspace observation queue capacity reached")
        if coalesced_fingerprint is not None:
            workspace.observation_fingerprints[event_type] = coalesced_fingerprint
        self._remember_key(workspace, idempotency_key)
        workspace.context_version += 1
        workspace.last_active_at = time.monotonic()
        if event_type == "ROUTE_CHANGED" and isinstance(clean.get("route"), str):
            workspace.current_route = str(clean["route"])
        if event_type == "QUERY_SUBMITTED" and isinstance(clean.get("query"), str):
            workspace.current_query = str(clean["query"])
        if event_type == "READINESS_CHANGED":
            self._apply_readiness(workspace, clean)
        observed_at = _iso()
        workspace.topic_graph.observe(event_type, clean, observed_at=observed_at)
        observation = WorkspaceObservation(
            workspace_id=workspace.workspace_id,
            user_id=user_id,
            mode=workspace.mode,
            context_version=workspace.context_version,
            event_type=event_type,
            payload=clean,
            context_route=workspace.current_route,
            context_query=workspace.current_query,
            context_top_topics=workspace.topic_graph.top_topics(),
            context_external_context=tuple(dict(item) for item in workspace.external_context),
            context_source_statuses=dict(workspace.source_statuses),
            context_personalization_enabled=workspace.personalization_enabled,
        )
        self._publish(workspace, "OBSERVATION_ACCEPTED", {
            "observation_type": event_type,
            "source": "kiosk",
            "context_version": workspace.context_version,
            "processing": "QUEUED" if dispatcher is not None else "RULE_FALLBACK",
        })
        if dispatcher is None:
            self._coordinate(workspace, event_type, clean)
            workspace.last_processed_context_version = workspace.context_version
        else:
            dispatcher.submit(observation)
        return self.snapshot(workspace_id, user_id=user_id), False

    async def wait_for_idle(self) -> None:
        """Test/acceptance seam; HTTP clients should observe completion over SSE."""

        if self._dispatcher is not None:
            await self._dispatcher.wait_idle()

    def directive_action(self, workspace_id: UUID, *, user_id: int, directive_id: UUID, action: str) -> dict[str, object]:
        workspace = self._visible(workspace_id, user_id)
        self._expire_directives(workspace)
        if action not in DIRECTIVE_ACTIONS:
            raise ValueError("directive action is not allowed")
        directive = workspace.directives.get(str(directive_id))
        if directive is None:
            raise WorkspaceNotFoundError("directive not found")
        next_status = {"ACCEPT": "ACCEPTED", "DISMISS": "DISMISSED", "UNDO": "UNDONE"}[action]
        current_status = str(directive.get("status", ""))
        if current_status == next_status:
            # A repeated button click is a safe idempotent replay.  Do not
            # generate another event or another audit fact.
            return dict(directive)
        if current_status not in {"PROPOSED", "AUTO_APPLIED", "ACCEPTED"}:
            raise WorkspaceConflictError("directive is no longer actionable")
        if action == "UNDO" and not bool(directive.get("reversible", False)):
            raise WorkspaceConflictError("directive is not reversible")
        directive["status"] = next_status
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
        payload = {
            "status": status,
            "task_id": str(task_id),
            **({"trace_id": str(trace_id)} if trace_id else {}),
        }
        self._publish(workspace, "RECOMMENDATION_COMPLETED", payload)
        self._queue_internal_observation(workspace, "RECOMMENDATION_COMPLETED", payload)

    def bridge_historical_actions(
        self,
        workspace_id: UUID,
        *,
        user_id: int,
        task_id: UUID,
        actions: object,
    ) -> int:
        """Restore persisted public Agent actions without dispatch or audit.

        This bridge is read-only and idempotent per Workspace/task.  Its events
        carry ``replayed=true`` so the kiosk cannot confuse them with live work.
        """
        workspace = self._visible(workspace_id, user_id)
        task_key = str(task_id)
        if task_key in workspace.replayed_task_ids or not isinstance(actions, list):
            return 0
        restored = 0
        for raw in actions[:32]:
            if not isinstance(raw, Mapping):
                continue
            clean = self._sanitize_payload(raw)
            name = str(clean.get("agent_name", ""))
            if name not in workspace.agents:
                continue
            self._set_agent(
                workspace,
                name,
                "COMPLETED",
                action=str(clean.get("action", "RETURN_RESULT")),
                target=str(clean.get("target", "RecommendationOrchestrator")),
                reason=str(clean.get("reason_code", "PERSISTED_ACTION_REPLAY")),
                confidence=clean.get("confidence"),
                duration_ms=None,
                evidence_refs=clean.get("evidence_refs"),
            )
            self._publish(
                workspace,
                "RECOMMENDATION_HISTORY_REPLAY",
                {
                    "replayed": True,
                    "task_id": task_key,
                    "agent_name": name,
                    "action": clean.get("action", "RETURN_RESULT"),
                    "target": clean.get("target", "RecommendationOrchestrator"),
                    "reason_code": clean.get("reason_code", "PERSISTED_ACTION_REPLAY"),
                    "confidence": clean.get("confidence"),
                    "evidence_refs": clean.get("evidence_refs", []),
                },
            )
            restored += 1
        workspace.replayed_task_ids.add(task_key)
        return restored

    def bridge_feedback_action(self, workspace_id: UUID, *, user_id: int, action: Mapping[str, object]) -> None:
        workspace = self._visible(workspace_id, user_id)
        clean = self._sanitize_payload(action)
        self._dispatch(workspace, "FeedbackLearningAgent", action=str(clean.get("action", "PROPOSE_PROFILE_DELTA")), target=str(clean.get("target", "UserProfileAgent")), reason=str(clean.get("reason_code", "FEEDBACK_RECORDED")), confidence=clean.get("confidence"), evidence_refs=clean.get("evidence_refs"))
        self._queue_internal_observation(workspace, "FEEDBACK_RECORDED", clean)

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

    def _queue_internal_observation(
        self,
        workspace: _Workspace,
        event_type: str,
        payload: Mapping[str, object],
    ) -> None:
        clean = self._sanitize_payload(payload)
        workspace.context_version += 1
        workspace.topic_graph.observe(event_type, clean, observed_at=_iso())
        observation = WorkspaceObservation(
            workspace_id=workspace.workspace_id,
            user_id=workspace.user_id,
            mode=workspace.mode,
            context_version=workspace.context_version,
            event_type=event_type,
            payload=clean,
            context_route=workspace.current_route,
            context_query=workspace.current_query,
            context_top_topics=workspace.topic_graph.top_topics(),
            context_external_context=tuple(dict(item) for item in workspace.external_context),
            context_source_statuses=dict(workspace.source_statuses),
            context_personalization_enabled=workspace.personalization_enabled,
        )
        dispatcher = self._runtime_dispatcher()
        self._publish(workspace, "OBSERVATION_ACCEPTED", {
            "observation_type": event_type,
            "source": "business_service",
            "context_version": workspace.context_version,
            "processing": "QUEUED" if dispatcher is not None else "RULE_FALLBACK",
        })
        if dispatcher is None:
            self._coordinate(workspace, event_type, clean)
            workspace.last_processed_context_version = workspace.context_version
        else:
            try:
                dispatcher.submit(observation)
            except WorkspaceObservationCapacityError:
                self._publish(workspace, "OBSERVATION_DEGRADED", {
                    "observation_type": event_type,
                    "reason_code": "INTERNAL_QUEUE_CAPACITY_FALLBACK",
                })
                self._coordinate(workspace, event_type, clean)
                workspace.last_processed_context_version = workspace.context_version

    def _runtime_dispatcher(self) -> WorkspaceObservationDispatcher | None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return None
        if self._dispatcher is None:
            self._dispatcher = WorkspaceObservationDispatcher(
                processor=self._process_observation,
                failure_handler=self._observation_failed,
                max_concurrent=self._max_concurrent_observations,
                max_pending=self._max_pending_observations,
            )
        return self._dispatcher

    def _observation_failed(
        self, observation: WorkspaceObservation, exc: Exception,
    ) -> None:
        workspace = self._workspaces.get(observation.workspace_id)
        if workspace is None:
            return
        workspace.orchestrator_status = "DEGRADED"
        workspace.current_observation = {
            "event_type": observation.event_type,
            "context_version": observation.context_version,
            "status": "FAILED",
        }
        self._publish(workspace, "OBSERVATION_FAILED", {
            "observation_type": observation.event_type,
            "observation_context_version": observation.context_version,
            "reason_code": "WORKSPACE_PROCESSING_FAILED",
            "error_type": type(exc).__name__,
        })

    async def _process_observation(self, observation: WorkspaceObservation) -> None:
        workspace = self._workspaces.get(observation.workspace_id)
        if workspace is None or workspace.user_id != observation.user_id:
            return
        if observation.context_version <= workspace.last_processed_context_version:
            self._publish(workspace, "OBSERVATION_SUPERSEDED", {
                "observation_type": observation.event_type,
                "observation_context_version": observation.context_version,
                "reason_code": "STALE_CONTEXT_VERSION",
            })
            return
        workspace.current_observation = {
            "event_type": observation.event_type,
            "context_version": observation.context_version,
            "status": "PROCESSING",
        }
        workspace.orchestrator_status = "WORKING"
        handlers = [
            handler for handler in self._handlers
            if observation.event_type in handler.observation_types
            and not (
                handler.agent_name == "UserProfileAgent"
                and not (
                    observation.context_personalization_enabled
                    and workspace.personalization_enabled
                )
            )
        ]
        had_failure = False
        had_degraded = False
        successful_handlers = 0
        for handler in handlers:
            decision_id = uuid4()
            started = time.perf_counter()
            self._set_agent(
                workspace,
                handler.agent_name,
                "WORKING",
                action=f"HANDLE_{observation.event_type}",
                target="RecommendationOrchestrator",
                reason="OBSERVATION_DISPATCHED",
            )
            self._publish(workspace, "AGENT_STARTED", {
                "decision_id": str(decision_id),
                "agent_name": handler.agent_name,
                "action": f"HANDLE_{observation.event_type}",
                "target": "RecommendationOrchestrator",
                "reason_code": "OBSERVATION_DISPATCHED",
                "observation_type": observation.event_type,
                "observation_context_version": observation.context_version,
                "replayed": False,
            })
            try:
                result = await handler.handle(observation, self._handler_context(workspace, observation))
            except Exception as exc:
                had_failure = True
                duration_ms = max(0, int((time.perf_counter() - started) * 1000))
                self._set_agent(
                    workspace, handler.agent_name, "FAILED",
                    action=f"HANDLE_{observation.event_type}",
                    target="RecommendationOrchestrator",
                    reason="WORKSPACE_HANDLER_FAILED",
                    duration_ms=duration_ms,
                )
                self._publish(workspace, "AGENT_FAILED", {
                    "decision_id": str(decision_id),
                    "agent_name": handler.agent_name,
                    "action": f"HANDLE_{observation.event_type}",
                    "target": "RecommendationOrchestrator",
                    "reason_code": "WORKSPACE_HANDLER_FAILED",
                    "error_type": type(exc).__name__,
                    "duration_ms": duration_ms,
                    "observation_context_version": observation.context_version,
                })
                continue
            handler_state = self._apply_handler_result(
                workspace,
                result,
                decision_id=decision_id,
                context_version=observation.context_version,
                measured_ms=max(0, int((time.perf_counter() - started) * 1000)),
            )
            had_failure = had_failure or handler_state == "FAILED"
            had_degraded = had_degraded or handler_state == "DEGRADED"
            if handler_state not in {"FAILED", "DEGRADED"}:
                successful_handlers += 1
        if self._background_planner is not None and observation.event_type in BACKGROUND_PLANNING_TRIGGERS:
            await self._run_background_planning(workspace, observation)
        workspace.last_processed_context_version = observation.context_version
        outcome = (
            "FAILED"
            if had_failure and not had_degraded and successful_handlers == 0
            else "DEGRADED"
            if had_failure or had_degraded
            else "SUCCESS"
        )
        workspace.current_observation = {
            "event_type": observation.event_type,
            "context_version": observation.context_version,
            "status": "FAILED" if outcome == "FAILED" else "DEGRADED" if outcome == "DEGRADED" else "COMPLETED",
        }
        workspace.orchestrator_status = "DEGRADED" if outcome != "SUCCESS" else "OBSERVING"
        self._publish(workspace, "OBSERVATION_COMPLETED", {
            "observation_type": observation.event_type,
            "observation_context_version": observation.context_version,
            "handler_count": len(handlers),
            "outcome": outcome,
        })

    async def _run_background_planning(
        self,
        workspace: _Workspace,
        observation: WorkspaceObservation,
    ) -> None:
        """Run an explicitly injected planner; the default broker has none."""

        async def announce(decision_id: UUID, context: SanitizedPlanningContext) -> None:
            self._set_agent(
                workspace,
                "RecommendationPolicyAgent",
                "PLANNING",
                action="BACKGROUND_PLAN",
                target="InteractionDirectiveEngine",
                reason="BACKGROUND_PLAN_TRIGGERED",
            )
            self._publish(workspace, "AGENT_STARTED", {
                "decision_id": str(decision_id),
                "agent_name": "RecommendationPolicyAgent",
                "action": "BACKGROUND_PLAN",
                "target": "InteractionDirectiveEngine",
                "reason_code": "BACKGROUND_PLAN_TRIGGERED",
                "observation_type": observation.event_type,
                "observation_context_version": context.context_version,
                "replayed": False,
                "llm_requests": 0,
            })

        profile_summary: Mapping[str, object] | None = None
        # Background planning receives a profile summary only for a formally
        # authenticated account with explicit personalization consent.  The
        # profile adapter is read-only and bounded; Guest, demo and
        # unauthorised sessions never invoke it here.  A temporary profile
        # read failure does not block the ambient policy path: the planner
        # receives anonymous context and the normal UserProfileAgent result
        # remains the source of any visible degradation signal.
        if (
            workspace.mode == "authenticated"
            and workspace.user_id >= 10_000
            and observation.context_personalization_enabled
            and workspace.personalization_enabled
            and self._profile_reader is not None
        ):
            try:
                profile_summary = await self._profile_reader.summary(workspace.user_id)
            except Exception:
                profile_summary = None

        context = PlanningContext(
            workspace_id=workspace.workspace_id,
            session_id=workspace.session_id,
            device_id=workspace.device_id,
            mode=workspace.mode,  # type: ignore[arg-type]
            context_version=observation.context_version,
            trigger=observation.event_type,
            route=observation.context_route,
            query=observation.context_query,
            top_topics=observation.context_top_topics,
            source_statuses=observation.context_source_statuses,
            external_context=observation.context_external_context,
            personalization_enabled=observation.context_personalization_enabled,
            profile_summary=profile_summary,
        )
        outcome = await self._background_planner.plan(
            context,
            idempotency_key=f"workspace:{workspace.workspace_id}:context:{observation.context_version}",
            on_dispatch=announce,
        )
        workspace.background_planning = self._public_background_outcome(outcome)
        if outcome.status == "SKIPPED":
            self._publish(workspace, "BACKGROUND_PLAN_SKIPPED", {
                "reason_code": outcome.reason_code,
                "observation_context_version": observation.context_version,
                "budget": self._public_budget(outcome),
            })
            return
        state = "COMPLETED" if outcome.status == "PLANNED" else outcome.status
        self._set_agent(
            workspace,
            "RecommendationPolicyAgent",
            state,
            action="BACKGROUND_PLAN",
            target="InteractionDirectiveEngine",
            reason=outcome.reason_code,
            confidence=outcome.confidence,
            duration_ms=0,
            evidence_refs=outcome.evidence_refs,
        )
        terminal = "AGENT_COMPLETED" if outcome.status in {"PLANNED", "DEGRADED"} else "AGENT_FAILED"
        self._publish(workspace, terminal, {
            "decision_id": str(outcome.decision_id) if outcome.decision_id else None,
            "agent_name": "RecommendationPolicyAgent",
            "action": "BACKGROUND_PLAN",
            "target": "InteractionDirectiveEngine",
            "reason_code": outcome.reason_code,
            "confidence": outcome.confidence,
            "duration_ms": 0,
            "evidence_refs": list(outcome.evidence_refs),
            "outcome": outcome.status,
            "observation_context_version": observation.context_version,
            "provider": outcome.provider,
            "model": outcome.model,
            "llm_requests": outcome.model_requests,
            "budget": self._public_budget(outcome),
        })
        for proposal in outcome.directives:
            self._propose(
                workspace,
                proposal.directive_type,
                proposal.scope,
                proposal.behavior,
                proposal.payload,
                proposal.reason_code,
                proposal.confidence,
                proposal.evidence_refs,
                reversible=proposal.reversible,
            )

    @staticmethod
    def _public_budget(outcome: BackgroundPlanningOutcome) -> dict[str, object] | None:
        budget = outcome.budget
        if budget is None:
            return None
        return {
            "session_calls": budget.session_calls,
            "session_limit": budget.session_limit,
            "device_calls_today": budget.device_calls_today,
            "device_limit_today": budget.device_limit_today,
            "next_allowed_at": _iso(budget.next_allowed_at) if budget.next_allowed_at else None,
        }

    @classmethod
    def _public_background_outcome(cls, outcome: BackgroundPlanningOutcome) -> dict[str, object]:
        return {
            "status": outcome.status,
            "reason_code": outcome.reason_code,
            "decision_id": str(outcome.decision_id) if outcome.decision_id else None,
            "context_version": outcome.context_version,
            "provider": outcome.provider,
            "model": outcome.model,
            "model_requests": outcome.model_requests,
            "directive_count": len(outcome.directives),
            "budget": cls._public_budget(outcome),
        }

    def _handler_context(
        self,
        workspace: _Workspace,
        observation: WorkspaceObservation | None = None,
    ) -> WorkspaceHandlerContext:
        route = observation.context_route if observation is not None else workspace.current_route
        query = observation.context_query if observation is not None else workspace.current_query
        top_topics = observation.context_top_topics if observation is not None else workspace.topic_graph.top_topics()
        external_context = observation.context_external_context if observation is not None else tuple(workspace.external_context)
        source_statuses = observation.context_source_statuses if observation is not None else dict(workspace.source_statuses)
        personalization_enabled = (
            observation.context_personalization_enabled
            if observation is not None
            else workspace.personalization_enabled
        )
        return WorkspaceHandlerContext(
            route=route,
            query=query,
            top_topics=top_topics,
            external_context=external_context,
            source_statuses=source_statuses,
            personalization_enabled=personalization_enabled,
        )

    def _apply_handler_result(
        self,
        workspace: _Workspace,
        result: WorkspaceAgentResult,
        *,
        decision_id: UUID,
        context_version: int,
        measured_ms: int,
    ) -> str:
        state = {
            "SUCCESS": "COMPLETED",
            "DEGRADED": "DEGRADED",
            "FAILED": "FAILED",
            "WAITING_USER": "WAITING_USER",
        }.get(result.outcome, "FAILED")
        for tool_call in result.tool_calls[:8]:
            self._publish(workspace, "AGENT_TOOL_CALL", {
                "decision_id": str(decision_id),
                "agent_name": result.agent_name,
                "tool_call": tool_call,
                "observation_context_version": context_version,
            })
        self._set_agent(
            workspace,
            result.agent_name,
            state,
            action=result.action,
            target=result.target,
            reason=result.reason_code,
            confidence=result.confidence,
            duration_ms=measured_ms,
            evidence_refs=result.evidence_refs,
        )
        terminal_event = "AGENT_COMPLETED" if state in {"COMPLETED", "DEGRADED"} else "AGENT_FAILED"
        self._publish(workspace, terminal_event, {
            "decision_id": str(decision_id),
            "agent_name": result.agent_name,
            "action": result.action,
            "target": result.target,
            "reason_code": result.reason_code,
            "confidence": result.confidence,
            "duration_ms": measured_ms,
            "evidence_refs": list(result.evidence_refs),
            "outcome": result.outcome,
            "observation_context_version": context_version,
        })
        for proposal in result.directives:
            self._propose(
                workspace,
                proposal.directive_type,
                proposal.scope,
                proposal.behavior,
                proposal.payload,
                proposal.reason_code,
                proposal.confidence,
                proposal.evidence_refs,
                reversible=proposal.reversible,
            )
        return state

    def _coordinate(self, workspace: _Workspace, event_type: str, payload: Mapping[str, object]) -> None:
        """Explicit no-event-loop fallback retained for offline dry-runs only."""
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
        if event_type == "SESSION_STARTED" and workspace.mode == "demo" and workspace.personalization_enabled:
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
        self._expire_directives(workspace)
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
        directive["updated_at"] = directive["created_at"]
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

    def _expire_directives(self, workspace: _Workspace) -> None:
        """Move elapsed directives to an explicit terminal state.

        Expiry is evaluated on reads and actions, so a stale suggestion cannot
        remain actionable merely because no new observation arrived.  The
        transition is append-only from the audit buffer's perspective and is
        emitted once per directive.
        """

        now = _utc_now()
        for directive in tuple(workspace.directives.values()):
            if str(directive.get("status")) not in {"PROPOSED", "AUTO_APPLIED", "ACCEPTED"}:
                continue
            expires_at = directive.get("expires_at")
            if not isinstance(expires_at, str):
                continue
            try:
                expires = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            except ValueError:
                continue
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=UTC)
            if expires > now:
                continue
            directive["status"] = "EXPIRED"
            directive["updated_at"] = _iso(now)
            self._publish(workspace, "DIRECTIVE_EXPIRED", {
                "directive_id": directive.get("directive_id"),
                "directive_type": directive.get("type"),
                "reason_code": "DIRECTIVE_TTL_EXPIRED",
            })
            self._capture_directive(workspace, directive)

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
