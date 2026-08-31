"""Low-frequency, event-triggered background Agent planning.

This module owns only policy and validation.  It never opens a database, emits
business writes, or constructs an LLM client.  A real DeepSeek adapter can be
injected later through :class:`BackgroundPlanningPort` under its own approved
request budget.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import inspect
import re
from threading import Lock
from typing import Awaitable, Callable, Iterable, Mapping, Sequence
from uuid import UUID, uuid4

from backend.app.agent_workspace.ports.handlers import WorkspaceDirectiveProposal
from backend.app.agent_workspace.ports.planning import (
    BACKGROUND_DIRECTIVE_TYPES,
    BACKGROUND_PLANNING_TRIGGERS,
    BackgroundPlanningOutcome,
    BackgroundPlanningPort,
    BackgroundPlanningResult,
    PlanningBudgetPort,
    PlanningBudgetSnapshot,
    PlanningContext,
    PlanningReservation,
    SanitizedPlanningContext,
)


_ALLOWED_BEHAVIORS = frozenset({"AUTO_APPLY", "SUGGESTION", "NOTICE"})
_ALLOWED_ROUTES = frozenset({"/", "/recommend", "/graph", "/path", "/insights"})
_ALLOWED_OUTPUT_TYPES = frozenset({"TOPIC_RESOURCES", "PERSONALIZED_FEED", "READING_PATH"})
_ALLOWED_ACTIONS = frozenset({"OPEN_RECOMMEND", "OPEN_GRAPH", "RECOMMEND_AGAIN"})
_ALLOWED_DENSITIES = frozenset({"DETAILED", "BALANCED", "COMPACT"})
_FORBIDDEN_KEYS = frozenset(
    {
        "prompt",
        "raw_prompt",
        "model_output",
        "sql",
        "cypher",
        "password",
        "secret",
        "api_key",
        "token",
        "identifier",
        "user_id",
        "profile",
    }
)
_SENSITIVE_TEXT = re.compile(
    r"(?:password|passwd|secret|api[_-]?key|bearer|token|sk-[A-Za-z0-9_-]{8,})",
    re.IGNORECASE,
)
_REASON_CODE = re.compile(r"^[A-Z0-9][A-Z0-9_:.-]{0,63}$")


@dataclass(frozen=True, slots=True)
class PlanningBudgetPolicy:
    """Explicit low-frequency policy selected for the research/production plan."""

    max_calls_per_session: int = 3
    min_interval_seconds: int = 10 * 60
    max_calls_per_device_day: int = 12

    def __post_init__(self) -> None:
        if not 1 <= self.max_calls_per_session <= 3:
            raise ValueError("session background planning limit must be between 1 and 3")
        if not 60 <= self.min_interval_seconds <= 24 * 60 * 60:
            raise ValueError("background planning interval is outside the safe bound")
        if not 1 <= self.max_calls_per_device_day <= 12:
            raise ValueError("device background planning limit must be between 1 and 12")


class InMemoryPlanningBudget(PlanningBudgetPort):
    """Process-local attempt budget; reservations are never refunded."""

    def __init__(self, policy: PlanningBudgetPolicy | None = None) -> None:
        self.policy = policy or PlanningBudgetPolicy()
        self._session_calls: dict[UUID, list[datetime]] = defaultdict(list)
        self._device_calls: dict[tuple[str, date], list[datetime]] = defaultdict(list)
        self._lock = Lock()

    def reserve(
        self,
        *,
        session_id: UUID,
        device_id: str,
        now: datetime,
    ) -> PlanningReservation:
        if now.tzinfo is None:
            raise ValueError("planning budget timestamps must be timezone-aware")
        clean_device = device_id.strip()[:128]
        if not clean_device:
            raise ValueError("planning device id must not be blank")
        with self._lock:
            session = self._session_calls[session_id]
            device_key = (clean_device, now.astimezone(UTC).date())
            device = self._device_calls[device_key]
            self._prune(device, datetime.combine(now.astimezone(UTC).date(), datetime.min.time(), tzinfo=UTC))
            last = session[-1] if session else None
            next_allowed = (
                last + timedelta(seconds=self.policy.min_interval_seconds)
                if last is not None
                else None
            )
            snapshot = PlanningBudgetSnapshot(
                session_calls=len(session),
                session_limit=self.policy.max_calls_per_session,
                device_calls_today=len(device),
                device_limit_today=self.policy.max_calls_per_device_day,
                last_call_at=last,
                next_allowed_at=next_allowed,
            )
            if len(session) >= self.policy.max_calls_per_session:
                return PlanningReservation(False, "SESSION_BACKGROUND_BUDGET_EXHAUSTED", snapshot)
            if len(device) >= self.policy.max_calls_per_device_day:
                return PlanningReservation(False, "DEVICE_BACKGROUND_BUDGET_EXHAUSTED", snapshot)
            if next_allowed is not None and now < next_allowed:
                return PlanningReservation(False, "BACKGROUND_PLANNING_INTERVAL_NOT_ELAPSED", snapshot)
            session.append(now)
            device.append(now)
            reserved = PlanningBudgetSnapshot(
                session_calls=len(session),
                session_limit=self.policy.max_calls_per_session,
                device_calls_today=len(device),
                device_limit_today=self.policy.max_calls_per_device_day,
                last_call_at=now,
                next_allowed_at=now + timedelta(seconds=self.policy.min_interval_seconds),
            )
            return PlanningReservation(True, "BACKGROUND_PLANNING_BUDGET_RESERVED", reserved)

    @staticmethod
    def _prune(values: list[datetime], cutoff: datetime) -> None:
        values[:] = [value for value in values if value >= cutoff]


class PlanningContextSanitizer:
    """Build the only context shape that a background model may receive."""

    _external_value_keys = frozenset(
        {"timezone", "opens_at", "closes_at", "phase", "suggested_topics", "topic", "event"}
    )
    _profile_keys = frozenset(
        {"profile_version", "major", "grade", "research_direction", "preferred_language", "confidence"}
    )

    def sanitize(self, context: PlanningContext) -> SanitizedPlanningContext:
        profile = None
        if context.personalization_enabled and context.profile_summary is not None:
            profile = {
                key: self._safe_value(value, max_length=160)
                for key, value in context.profile_summary.items()
                if key in self._profile_keys and key not in _FORBIDDEN_KEYS
            }
            if not profile:
                profile = None
        external: list[Mapping[str, object]] = []
        for raw in context.external_context[:8]:
            if not isinstance(raw, Mapping):
                continue
            values = raw.get("values")
            safe_values = {
                str(key): self._safe_value(value, max_length=160)
                for key, value in (values.items() if isinstance(values, Mapping) else ())
                if str(key) in self._external_value_keys
            }
            external.append(
                {
                    "source_id": self._safe_text(raw.get("source_id", "external"), 80),
                    "kind": "EXTERNAL_DEMO",
                    "label": self._safe_text(raw.get("label", "演示外部情境"), 120),
                    "status": self._safe_text(raw.get("status", "UNKNOWN"), 24),
                    "observed_at": self._safe_text(raw.get("observed_at", ""), 40),
                    "expires_at": self._safe_text(raw.get("expires_at", ""), 40),
                    "values": safe_values,
                }
            )
        statuses = {
            self._safe_text(key, 32): self._safe_text(value, 24)
            for key, value in list(context.source_statuses.items())[:8]
            if not _SENSITIVE_TEXT.search(str(key))
        }
        return SanitizedPlanningContext(
            mode=context.mode,
            context_version=context.context_version,
            trigger=context.trigger,
            route=context.route if context.route in _ALLOWED_ROUTES else "/",
            query=self._safe_query(context.query),
            top_topics=tuple(self._safe_text(item, 80) for item in context.top_topics[:8] if str(item).strip()),
            source_statuses=statuses,
            external_context=tuple(external),
            profile_summary=profile,
        )

    @staticmethod
    def _safe_text(value: object, max_length: int) -> str:
        text = " ".join(str(value or "").split())[:max_length]
        return "[已过滤]" if _SENSITIVE_TEXT.search(text) else text

    def _safe_query(self, value: object) -> str:
        text = self._safe_text(value, 240)
        return text if text != "[已过滤]" else ""

    @classmethod
    def _safe_value(cls, value: object, *, max_length: int) -> object:
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            text = " ".join(value.split())[:max_length]
            return "[已过滤]" if _SENSITIVE_TEXT.search(text) else text
        if isinstance(value, (list, tuple)):
            return [cls._safe_value(item, max_length=max_length) for item in value[:12] if isinstance(item, (str, int, float, bool))]
        return "[已过滤]"


class DirectiveValidationError(ValueError):
    """A model returned a directive outside the public interaction contract."""


class DirectiveValidator:
    """Strictly decode model output into existing Workspace proposals."""

    def validate(self, directives: Sequence[object]) -> tuple[WorkspaceDirectiveProposal, ...]:
        if len(directives) > 7:
            raise DirectiveValidationError("background planner returned too many directives")
        validated: list[WorkspaceDirectiveProposal] = []
        for raw in directives:
            if isinstance(raw, WorkspaceDirectiveProposal):
                candidate: Mapping[str, object] = {
                    "directive_type": raw.directive_type,
                    "scope": raw.scope,
                    "behavior": raw.behavior,
                    "payload": raw.payload,
                    "reason_code": raw.reason_code,
                    "confidence": raw.confidence,
                    "evidence_refs": raw.evidence_refs,
                    "reversible": raw.reversible,
                }
            elif isinstance(raw, Mapping):
                candidate = raw
            else:
                raise DirectiveValidationError("background directive must be an object")
            self._validate_keys(candidate)
            directive_type = self._text(candidate.get("directive_type") or candidate.get("type"), 64)
            if directive_type not in BACKGROUND_DIRECTIVE_TYPES:
                raise DirectiveValidationError("background directive type is not allow-listed")
            scope = self._text(candidate.get("scope"), 80)
            behavior = self._text(candidate.get("behavior"), 16)
            if behavior not in _ALLOWED_BEHAVIORS:
                raise DirectiveValidationError("background directive behavior is invalid")
            payload = candidate.get("payload")
            if not isinstance(payload, Mapping):
                raise DirectiveValidationError("background directive payload must be an object")
            clean_payload = self._payload(directive_type, payload)
            reason = self._text(candidate.get("reason_code"), 64)
            if _REASON_CODE.fullmatch(reason) is None:
                raise DirectiveValidationError("background directive reason code is invalid")
            confidence = candidate.get("confidence")
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
                raise DirectiveValidationError("background directive confidence is invalid")
            evidence = candidate.get("evidence_refs", ())
            if not isinstance(evidence, (list, tuple)) or len(evidence) > 8:
                raise DirectiveValidationError("background directive evidence is invalid")
            evidence_refs = tuple(self._text(item, 160) for item in evidence)
            if any(not item or _SENSITIVE_TEXT.search(item) for item in evidence_refs):
                raise DirectiveValidationError("background directive evidence contains unsafe text")
            reversible = candidate.get("reversible", True)
            if not isinstance(reversible, bool):
                raise DirectiveValidationError("background directive reversible flag is invalid")
            validated.append(WorkspaceDirectiveProposal(
                directive_type=directive_type,
                scope=scope or "global",
                behavior=behavior,
                payload=clean_payload,
                reason_code=reason,
                confidence=float(confidence),
                evidence_refs=evidence_refs,
                reversible=reversible,
            ))
        return tuple(validated)

    @staticmethod
    def _validate_keys(candidate: Mapping[str, object]) -> None:
        allowed = {"directive_type", "type", "scope", "behavior", "payload", "reason_code", "confidence", "evidence_refs", "reversible"}
        if set(candidate) - allowed:
            raise DirectiveValidationError("background directive contains an unknown field")
        if any(str(key).lower() in _FORBIDDEN_KEYS for key in candidate):
            raise DirectiveValidationError("background directive contains a forbidden field")

    @classmethod
    def _payload(cls, directive_type: str, payload: Mapping[str, object]) -> dict[str, object]:
        if len(payload) > 8 or any(str(key).lower() in _FORBIDDEN_KEYS for key in payload):
            raise DirectiveValidationError("background directive payload is outside the allowlist")
        clean: dict[str, object] = {}
        for key, value in payload.items():
            if not isinstance(key, str) or len(key) > 64:
                raise DirectiveValidationError("background directive payload key is invalid")
            if isinstance(value, Mapping):
                raise DirectiveValidationError("nested directive payloads are not allowed")
            if isinstance(value, (list, tuple)):
                if len(value) > 12 or any(not isinstance(item, (str, int, float, bool)) for item in value):
                    raise DirectiveValidationError("directive list value is invalid")
                clean[key] = [cls._value(item) for item in value]
            else:
                clean[key] = cls._value(value)
        if directive_type == "SUGGEST_TOPICS":
            topics = clean.get("topics")
            if not isinstance(topics, list) or not all(isinstance(item, str) and item for item in topics):
                raise DirectiveValidationError("topic suggestions are invalid")
            clean["topics"] = topics[:8]
        elif directive_type == "SET_PRIMARY_ENTRY":
            if clean.get("route") not in _ALLOWED_ROUTES:
                raise DirectiveValidationError("primary route is not allow-listed")
        elif directive_type == "PREFER_OUTPUT_TYPE":
            if clean.get("output_type") not in _ALLOWED_OUTPUT_TYPES:
                raise DirectiveValidationError("output type is not allow-listed")
        elif directive_type == "SET_EXPLANATION_DENSITY":
            if clean.get("density") not in _ALLOWED_DENSITIES:
                raise DirectiveValidationError("explanation density is not allow-listed")
        elif directive_type == "SUGGEST_NEXT_ACTION":
            if clean.get("action") not in _ALLOWED_ACTIONS:
                raise DirectiveValidationError("next action is not allow-listed")
        elif directive_type == "SHOW_GUIDANCE":
            if not isinstance(clean.get("message"), str) or not clean["message"]:
                raise DirectiveValidationError("guidance message is required")
        elif directive_type == "SHOW_DEGRADED_NOTICE":
            components = clean.get("components")
            if not isinstance(components, list) or not all(isinstance(item, str) for item in components):
                raise DirectiveValidationError("degraded components are invalid")
        return clean

    @staticmethod
    def _value(value: object) -> object:
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            text = " ".join(value.split())[:240]
            if _SENSITIVE_TEXT.search(text):
                raise DirectiveValidationError("directive payload contains sensitive text")
            return text
        raise DirectiveValidationError("directive payload value is invalid")

    @staticmethod
    def _text(value: object, max_length: int) -> str:
        if not isinstance(value, str):
            raise DirectiveValidationError("directive text field is invalid")
        text = " ".join(value.split())[:max_length]
        if _SENSITIVE_TEXT.search(text):
            raise DirectiveValidationError("directive text contains sensitive content")
        return text


class FixtureBackgroundPlanner(BackgroundPlanningPort):
    """Deterministic local planner used before a real model budget is approved."""

    async def plan(self, context: SanitizedPlanningContext) -> BackgroundPlanningResult:
        directives: list[WorkspaceDirectiveProposal] = []
        topics = list(dict.fromkeys((*context.top_topics, *self._external_topics(context))))[:8]
        if topics:
            directives.append(WorkspaceDirectiveProposal(
                "SUGGEST_TOPICS", "home", "SUGGESTION", {"topics": topics},
                "BACKGROUND_CONTEXT_TOPICS", 0.86, ("workspace:context",), True,
            ))
        if context.route == "/path":
            directives.append(WorkspaceDirectiveProposal(
                "PREFER_OUTPUT_TYPE", "/path", "SUGGESTION", {"output_type": "READING_PATH"},
                "BACKGROUND_ROUTE_READING_PATH", 0.82, ("session:route",), True,
            ))
        degraded = [name for name, status in context.source_statuses.items() if status not in {"UP", "UNKNOWN"}]
        if degraded:
            directives.append(WorkspaceDirectiveProposal(
                "SHOW_DEGRADED_NOTICE", "global", "NOTICE", {
                    "components": degraded[:8],
                    "message": "部分检索通道暂不可用，仍可使用当前可用数据继续探索。",
                }, "BACKGROUND_SOURCE_DEGRADED", 1.0,
                tuple(f"readiness:{name}" for name in degraded[:8]), False,
            ))
        return BackgroundPlanningResult(
            directives=tuple(directives),
            evidence_refs=("workspace:context", "policy:background-fixture-v1"),
            confidence=0.86 if directives else 0.76,
            provider="fixture",
            model="background-rule-v1",
            model_requests=0,
        )

    @staticmethod
    def _external_topics(context: SanitizedPlanningContext) -> Iterable[str]:
        for source in context.external_context:
            values = source.get("values")
            if not isinstance(values, Mapping):
                continue
            suggested = values.get("suggested_topics")
            if isinstance(suggested, list):
                yield from (item for item in suggested if isinstance(item, str))
            topic = values.get("topic")
            if isinstance(topic, str):
                yield topic


DispatchCallback = Callable[[UUID, SanitizedPlanningContext], Awaitable[None] | None]


class BackgroundPlanningCoordinator:
    """Apply trigger, version, budget and schema boundaries around a planner."""

    def __init__(
        self,
        *,
        planner: BackgroundPlanningPort,
        budget: PlanningBudgetPort | None = None,
        sanitizer: PlanningContextSanitizer | None = None,
        validator: DirectiveValidator | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._planner = planner
        self._budget = budget or InMemoryPlanningBudget()
        self._sanitizer = sanitizer or PlanningContextSanitizer()
        self._validator = validator or DirectiveValidator()
        self._clock = clock
        self._last_versions: dict[UUID, int] = {}
        self._keys: set[str] = set()
        self._key_order: deque[str] = deque(maxlen=2048)
        self._lock = asyncio.Lock()

    async def plan(
        self,
        context: PlanningContext,
        *,
        idempotency_key: str | None = None,
        on_dispatch: DispatchCallback | None = None,
    ) -> BackgroundPlanningOutcome:
        if context.trigger not in BACKGROUND_PLANNING_TRIGGERS:
            return BackgroundPlanningOutcome(
                "SKIPPED", "BACKGROUND_TRIGGER_NOT_ELIGIBLE", None, context.context_version,
            )
        key = idempotency_key or f"{context.session_id}:{context.trigger}:{context.context_version}"
        # Admission is serialized, but the actual planner call is deliberately
        # outside this lock.  A slow model (or a test double simulating one)
        # must not block unrelated workspaces from reserving their own bounded
        # slot.  The key is recorded before dispatch, so concurrent replays are
        # still rejected without holding a global lock over I/O.
        async with self._lock:
            if key in self._keys or context.context_version <= self._last_versions.get(context.session_id, 0):
                return BackgroundPlanningOutcome(
                    "SKIPPED", "BACKGROUND_OBSERVATION_ALREADY_PLANNED", None, context.context_version,
                )
            self._keys.add(key)
            self._key_order.append(key)
            if len(self._key_order) == self._key_order.maxlen:
                # ``deque(maxlen=...)`` evicts before we can inspect the old
                # value, so rebuild the set from the bounded key order.  The
                # per-session version map remains the authoritative replay
                # guard after a key ages out.
                self._keys = set(self._key_order)
            sanitized = self._sanitizer.sanitize(context)
            reservation = self._budget.reserve(
                session_id=context.session_id,
                device_id=context.device_id,
                now=self._clock(),
            )
            if not reservation.allowed:
                return BackgroundPlanningOutcome(
                    "SKIPPED", reservation.reason_code, None, context.context_version,
                    budget=reservation.snapshot,
                )
            decision_id = uuid4()
        if on_dispatch is not None:
            callback_result = on_dispatch(decision_id, sanitized)
            if inspect.isawaitable(callback_result):
                await callback_result
        try:
            raw_result = await self._planner.plan(sanitized)
            directives = self._validator.validate(raw_result.directives)
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            async with self._lock:
                self._last_versions[context.session_id] = context.context_version
            return BackgroundPlanningOutcome(
                "DEGRADED", "BACKGROUND_MODEL_TIMEOUT", decision_id, context.context_version,
                provider="unknown", model="unknown", model_requests=1, budget=reservation.snapshot,
            )
        except DirectiveValidationError:
            async with self._lock:
                self._last_versions[context.session_id] = context.context_version
            return BackgroundPlanningOutcome(
                "DEGRADED", "BACKGROUND_DIRECTIVE_INVALID", decision_id, context.context_version,
                provider="unknown", model="unknown", model_requests=1, budget=reservation.snapshot,
            )
        except Exception as exc:
            async with self._lock:
                self._last_versions[context.session_id] = context.context_version
            reason_code = {
                "DeepSeekRequestError": "BACKGROUND_MODEL_TRANSPORT_FAILED",
                "DeepSeekPayloadError": "BACKGROUND_MODEL_PAYLOAD_INVALID",
                "PromptBundleError": "BACKGROUND_MODEL_CONTRACT_INVALID",
            }.get(type(exc).__name__, "BACKGROUND_PLANNER_FAILED")
            return BackgroundPlanningOutcome(
                "DEGRADED", reason_code, decision_id, context.context_version,
                provider="unknown", model="unknown", model_requests=1, budget=reservation.snapshot,
            )
        async with self._lock:
            self._last_versions[context.session_id] = context.context_version
        return BackgroundPlanningOutcome(
            "PLANNED", "BACKGROUND_PLAN_READY", decision_id, context.context_version,
            directives=directives,
            evidence_refs=tuple(raw_result.evidence_refs[:8]),
            confidence=max(0.0, min(1.0, float(raw_result.confidence))),
            provider=raw_result.provider[:64], model=raw_result.model[:128],
            model_requests=max(0, min(1, int(raw_result.model_requests))),
            budget=reservation.snapshot,
        )


__all__ = [
    "BackgroundPlanningCoordinator",
    "DirectiveValidationError",
    "DirectiveValidator",
    "FixtureBackgroundPlanner",
    "InMemoryPlanningBudget",
    "PlanningBudgetPolicy",
    "PlanningContextSanitizer",
]
