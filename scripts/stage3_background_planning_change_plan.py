#!/usr/bin/env python3
"""Freeze and execute the Stage 3 dual-identity background-planning probe.

``build`` runs the complete HTTP/Workspace flow with an in-memory model fixture
and writes a canonical ChangePlan. ``apply`` may issue at most two external
DeepSeek requests: one anonymous Guest Workspace and one formally authenticated
reader Workspace. No persistence, catalog, feedback, recommendation, graph or
vector adapter is composed.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker

from backend.app.agent_workspace import AgentWorkspaceBroker, BackgroundPlanningCoordinator
from backend.app.agent_workspace.adapters.deepseek_planner import (
    BackgroundPlanningModelPort,
    DeepSeekBackgroundPlanner,
)
from backend.app.agent_workspace.context import ContextObservation
from backend.app.config import AppSettings
from backend.app.llm.adapters.deepseek import DeepSeekLLMProvider
from backend.app.llm.ports.public import LLMResult
from backend.app.llm.prompts import load_prompt_bundle
from backend.app.main import create_app
from backend.app.shared_kernel.contracts.auth import AuthenticatedPrincipal


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "contracts/safety/change-plan.schema.json"
PROMPT_PATH = ROOT / "contracts/prompts/background-planning-prompts-v1.json"
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
CONFIRMATION = "YES_STAGE3_DUAL_BACKGROUND_DEEPSEEK"
FORMAL_READER_ID = 10_001
MAX_EXTERNAL_REQUESTS = 2
FIXED_OBSERVED_AT = datetime(2026, 9, 13, 0, 0, tzinfo=UTC)
FORBIDDEN_CONTEXT_KEYS = frozenset(
    {"user_id", "identifier", "password", "token", "secret", "api_key", "prompt", "sql", "cypher"}
)
SENSITIVE_SENTINEL = "stage3-sensitive-value-must-not-pass"
AUTHORIZATION_TOKEN = "stage3-bounded-reader-token"


class Stage3AcceptanceFailure(RuntimeError):
    """Carry only bounded public failure evidence."""

    def __init__(
        self,
        reason_code: str,
        *,
        external_requests: int,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.external_requests = external_requests
        self.details = dict(details or {})


def canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    value = result.stdout.strip()
    if re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise ValueError("Git HEAD is invalid")
    return value


def require_clean_worktree() -> None:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    if result.stdout.strip():
        raise ValueError("worktree must be clean before build or apply")


def resolve_inside_root(path: Path, *, label: str) -> Path:
    resolved = (path if path.is_absolute() else ROOT / path).resolve(strict=True)
    try:
        resolved.relative_to(ROOT)
    except ValueError as exc:
        raise ValueError(f"{label} must resolve inside the repository") from exc
    return resolved


def identities(run_id: str, commit: str) -> dict[str, object]:
    prefix = f"stage3-background:{commit}:{run_id}"
    return {
        "guest": {
            "session_id": str(uuid5(NAMESPACE_URL, f"{prefix}:guest-session")),
            "workspace_id": str(uuid5(NAMESPACE_URL, f"{prefix}:guest-workspace")),
            "device_id": "stage3-approved-library-screen",
            "mode": "guest",
        },
        "authenticated": {
            "session_id": str(uuid5(NAMESPACE_URL, f"{prefix}:reader-session")),
            "workspace_id": str(uuid5(NAMESPACE_URL, f"{prefix}:reader-workspace")),
            "device_id": "stage3-approved-library-screen",
            "mode": "authenticated",
            "user_id": FORMAL_READER_ID,
        },
    }


class _FixedExternalContextProvider:
    timeout_seconds = 1.0

    def read(self, *, now: datetime) -> ContextObservation:
        del now
        return ContextObservation(
            source_id="stage3-reviewed-library-context",
            kind="EXTERNAL_DEMO",
            label="阶段三审核情境",
            status="UP",
            observed_at=FIXED_OBSERVED_AT,
            expires_at=FIXED_OBSERVED_AT + timedelta(minutes=5),
            values={
                "phase": "论文研究期",
                "suggested_topics": ["多智能体", "智慧图书馆", "推荐系统"],
            },
        )


class _BoundedProfileReader:
    """In-memory consented summary used to exercise the formal identity path."""

    def __init__(self) -> None:
        self.calls: list[int] = []

    async def summary(self, user_id: int) -> Mapping[str, object]:
        self.calls.append(user_id)
        if user_id != FORMAL_READER_ID:
            raise ValueError("unexpected formal reader")
        return {
            "profile_version": "stage3-readonly-v1",
            "major": "图书馆学",
            "grade": "研究生",
            "research_direction": "多智能体推荐",
            "preferred_language": "zh-CN",
            "confidence": 0.88,
            # These fields prove the sanitizer removes identity and secret-like
            # data before the model adapter receives the context.
            "user_id": user_id,
            "password": SENSITIVE_SENTINEL,
        }


class _FixturePlanningModel(BackgroundPlanningModelPort):
    async def plan_workspace_background(self, context_json: str) -> LLMResult:
        context = json.loads(context_json)
        topic = "智慧图书馆" if context.get("mode") == "guest" else "多智能体推荐"
        return LLMResult(
            provider="fixture",
            model="stage3-background-fixture-v1",
            prompt_version="prompt-v3",
            prompt_id="workspace.background_plan",
            payload={"suggested_topics": [topic]},
        )


class _RecordingModel(BackgroundPlanningModelPort):
    """Enforce the total request ceiling before delegating to a model port."""

    def __init__(self, delegate: BackgroundPlanningModelPort) -> None:
        self._delegate = delegate
        self.contexts: list[str] = []

    async def plan_workspace_background(self, context_json: str) -> LLMResult:
        if len(self.contexts) >= MAX_EXTERNAL_REQUESTS:
            raise RuntimeError("stage3 external request budget exhausted")
        self._validate_context(context_json)
        self.contexts.append(context_json)
        return await self._delegate.plan_workspace_background(context_json)

    @staticmethod
    def _validate_context(context_json: str) -> None:
        if len(context_json) > 3000:
            raise ValueError("model context exceeds 3000 characters")
        if SENSITIVE_SENTINEL in context_json or AUTHORIZATION_TOKEN in context_json:
            raise ValueError("sensitive marker reached the model boundary")
        payload = json.loads(context_json)

        def walk(value: object) -> None:
            if isinstance(value, Mapping):
                for key, item in value.items():
                    if str(key).lower() in FORBIDDEN_CONTEXT_KEYS:
                        raise ValueError("forbidden key reached the model boundary")
                    walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)

        walk(payload)


def _principal_resolver(token: str, session_id: UUID) -> AuthenticatedPrincipal | None:
    if token != AUTHORIZATION_TOKEN:
        return None
    return AuthenticatedPrincipal(
        user_id=FORMAL_READER_ID,
        roles=frozenset({"user"}),
        token_id="stage3-bounded-reader-jti",
        session_id=session_id,
        auth_version=1,
        role_version=1,
        permissions=frozenset({"workspace.self.use", "personalization.profile.use"}),
    )


def _wait_for_background(
    client: TestClient,
    workspace_id: str,
    *,
    headers: Mapping[str, str] | None,
    timeout_seconds: float,
    request_count: Callable[[], int],
) -> Mapping[str, object]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        response = client.get(
            f"/api/v1/agent-workspaces/{workspace_id}",
            headers=dict(headers or {}),
        )
        if response.status_code != 200:
            raise Stage3AcceptanceFailure(
                "WORKSPACE_SNAPSHOT_FAILED",
                external_requests=request_count(),
                details={"status_code": response.status_code},
            )
        snapshot = response.json()
        background = snapshot.get("context_summary", {}).get("background_planning")
        if isinstance(background, Mapping) and background.get("status") in {
            "PLANNED", "DEGRADED", "FAILED"
        }:
            return snapshot
        time.sleep(0.1)
    raise Stage3AcceptanceFailure(
        "WORKSPACE_PLANNING_TIMEOUT",
        external_requests=request_count(),
    )


def _public_workspace_evidence(snapshot: Mapping[str, object]) -> dict[str, object]:
    context_summary = snapshot.get("context_summary")
    background = (
        context_summary.get("background_planning")
        if isinstance(context_summary, Mapping)
        else None
    )
    if not isinstance(background, Mapping):
        raise ValueError("background outcome is missing")
    events = snapshot.get("recent_events")
    public_events = [event for event in events if isinstance(event, Mapping)] if isinstance(events, list) else []
    planning_events = [
        event for event in public_events
        if event.get("action") == "BACKGROUND_PLAN"
    ]
    evidence = {
        "workspace_id": snapshot.get("workspace_id"),
        "mode": snapshot.get("mode"),
        "context_version": background.get("context_version"),
        "status": background.get("status"),
        "reason_code": background.get("reason_code"),
        "decision_id": background.get("decision_id"),
        "provider": background.get("provider"),
        "model": background.get("model"),
        "attempted_provider": background.get("attempted_provider"),
        "fallback_used": background.get("fallback_used"),
        "model_requests": background.get("model_requests"),
        "directive_count": background.get("directive_count"),
        "duration_ms": background.get("duration_ms"),
        "evidence_refs": background.get("evidence_refs"),
        "budget": background.get("budget"),
        "planning_event_types": [event.get("event_type") for event in planning_events],
    }
    encoded = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
    if SENSITIVE_SENTINEL in encoded or AUTHORIZATION_TOKEN in encoded:
        raise ValueError("sensitive data reached public Workspace evidence")
    return evidence


def run_dual_workspace_probe(
    *,
    model: BackgroundPlanningModelPort,
    run_id: str,
    commit: str,
    timeout_seconds: float,
) -> dict[str, object]:
    ids = identities(run_id, commit)
    guest = ids["guest"]
    authenticated = ids["authenticated"]
    if not isinstance(guest, Mapping) or not isinstance(authenticated, Mapping):
        raise ValueError("stage3 identities are malformed")
    workspace_ids = iter((UUID(str(guest["workspace_id"])), UUID(str(authenticated["workspace_id"]))))
    recorder = _RecordingModel(model)
    profile_reader = _BoundedProfileReader()
    broker = AgentWorkspaceBroker(
        context_providers=(_FixedExternalContextProvider(),),
        profile_reader=profile_reader,
        background_planner=BackgroundPlanningCoordinator(
            planner=DeepSeekBackgroundPlanner(recorder),
        ),
        workspace_id_factory=lambda: next(workspace_ids),
    )
    reader_session_id = UUID(str(authenticated["session_id"]))
    settings = AppSettings(app_env="demo", mysql_password="stage3-no-database-composed")
    application = create_app(
        settings=settings,
        principal_resolver=lambda token: _principal_resolver(token, reader_session_id),
        agent_workspace_broker=broker,
        background_planning_enabled=True,
        background_planning_version="background-planning-deepseek-topics-v1",
        background_planning_provider="DeepSeekBackgroundPlanner",
        managed_resources=(broker,),
    )
    try:
        with TestClient(application) as client:
            guest_response = client.post(
                "/api/v1/agent-workspaces",
                json={
                    "session_id": guest["session_id"],
                    "mode": "guest",
                    "device_id": guest["device_id"],
                },
            )
            if guest_response.status_code != 202:
                raise Stage3AcceptanceFailure(
                    "GUEST_WORKSPACE_CREATE_FAILED",
                    external_requests=len(recorder.contexts),
                    details={"status_code": guest_response.status_code},
                )
            guest_snapshot = _wait_for_background(
                client,
                str(guest["workspace_id"]),
                headers=None,
                timeout_seconds=timeout_seconds,
                request_count=lambda: len(recorder.contexts),
            )
            guest_evidence = _public_workspace_evidence(guest_snapshot)
            if guest_evidence["status"] != "PLANNED":
                raise Stage3AcceptanceFailure(
                    "GUEST_BACKGROUND_PLAN_NOT_READY",
                    external_requests=len(recorder.contexts),
                    details={
                        "status": guest_evidence["status"],
                        "reason_code": guest_evidence["reason_code"],
                    },
                )

            auth_headers = {"Authorization": f"Bearer {AUTHORIZATION_TOKEN}"}
            reader_response = client.post(
                "/api/v1/agent-workspaces",
                headers=auth_headers,
                json={
                    "session_id": authenticated["session_id"],
                    "mode": "authenticated",
                    "device_id": authenticated["device_id"],
                },
            )
            if reader_response.status_code != 202:
                raise Stage3AcceptanceFailure(
                    "READER_WORKSPACE_CREATE_FAILED",
                    external_requests=len(recorder.contexts),
                    details={"status_code": reader_response.status_code},
                )
            reader_snapshot = _wait_for_background(
                client,
                str(authenticated["workspace_id"]),
                headers=auth_headers,
                timeout_seconds=timeout_seconds,
                request_count=lambda: len(recorder.contexts),
            )
            reader_evidence = _public_workspace_evidence(reader_snapshot)
            if reader_evidence["status"] != "PLANNED":
                raise Stage3AcceptanceFailure(
                    "READER_BACKGROUND_PLAN_NOT_READY",
                    external_requests=len(recorder.contexts),
                    details={
                        "status": reader_evidence["status"],
                        "reason_code": reader_evidence["reason_code"],
                    },
                )
    except Stage3AcceptanceFailure:
        raise
    except Exception as exc:
        raise Stage3AcceptanceFailure(
            "STAGE3_RUNTIME_FAILED",
            external_requests=len(recorder.contexts),
            details={"error_type": type(exc).__name__},
        ) from exc

    if len(recorder.contexts) != MAX_EXTERNAL_REQUESTS:
        raise Stage3AcceptanceFailure(
            "STAGE3_REQUEST_COUNT_MISMATCH",
            external_requests=len(recorder.contexts),
        )
    parsed_contexts = [json.loads(value) for value in recorder.contexts]
    if parsed_contexts[0].get("mode") != "guest" or parsed_contexts[0].get("profile_summary") is not None:
        raise Stage3AcceptanceFailure(
            "GUEST_CONTEXT_NOT_ANONYMOUS",
            external_requests=len(recorder.contexts),
        )
    reader_profile = parsed_contexts[1].get("profile_summary")
    if parsed_contexts[1].get("mode") != "authenticated" or not isinstance(reader_profile, Mapping):
        raise Stage3AcceptanceFailure(
            "READER_CONTEXT_NOT_PERSONALIZED",
            external_requests=len(recorder.contexts),
        )
    allowed_profile_keys = {
        "profile_version", "major", "grade", "research_direction",
        "preferred_language", "confidence",
    }
    if set(reader_profile) - allowed_profile_keys:
        raise Stage3AcceptanceFailure(
            "READER_CONTEXT_PROFILE_EXCEEDED_ALLOWLIST",
            external_requests=len(recorder.contexts),
        )
    if set(profile_reader.calls) != {FORMAL_READER_ID}:
        raise Stage3AcceptanceFailure(
            "PROFILE_READER_IDENTITY_MISMATCH",
            external_requests=len(recorder.contexts),
        )
    context_evidence = [
        {
            "mode": parsed.get("mode"),
            "sha256": digest(raw.encode("utf-8")),
            "char_count": len(raw),
            "profile_present": isinstance(parsed.get("profile_summary"), Mapping),
            "profile_keys": sorted(parsed["profile_summary"])
            if isinstance(parsed.get("profile_summary"), Mapping)
            else [],
        }
        for raw, parsed in zip(recorder.contexts, parsed_contexts, strict=True)
    ]
    return {
        "workspaces": [guest_evidence, reader_evidence],
        "model_contexts": context_evidence,
        "external_requests": len(recorder.contexts),
        "formal_profile_read_count": len(profile_reader.calls),
        "formal_profile_reader_user_id": FORMAL_READER_ID,
        "database_connections": 0,
        "database_writes": 0,
        "neo4j_writes": 0,
        "chroma_writes": 0,
        "business_posts": 0,
    }


def load_settings(path: Path) -> AppSettings:
    settings = AppSettings(_env_file=str(path.resolve(strict=True)))
    if settings.app_env != "demo":
        raise ValueError("Stage 3 real planning is restricted to the demo research runtime")
    if settings.llm_provider != "deepseek" or settings.llm_api_key is None:
        raise ValueError("Stage 3 requires configured DeepSeek credentials")
    if settings.llm_model != "deepseek-v4-flash":
        raise ValueError("Stage 3 requires deepseek-v4-flash")
    if settings.llm_timeout_seconds > 20:
        raise ValueError("Stage 3 timeout must not exceed 20 seconds")
    return settings


def model_policy(settings: AppSettings) -> dict[str, object]:
    return {
        "provider": "deepseek",
        "model": settings.llm_model,
        "base_url": settings.llm_base_url,
        "timeout_seconds": settings.llm_timeout_seconds,
        "max_output_tokens_per_request": min(settings.llm_max_output_tokens, 256),
        "max_attempts_per_workspace": 1,
        "maximum_external_requests": MAX_EXTERNAL_REQUESTS,
        "maximum_billed_output_tokens": 2 * min(settings.llm_max_output_tokens, 256),
        "maximum_context_chars": 6000,
        "per_session_limit": 3,
        "minimum_interval_seconds": 600,
        "per_device_day_limit": 12,
        "allowed_directive_types": [
            "SUGGEST_TOPICS", "SET_PRIMARY_ENTRY", "PREFER_OUTPUT_TYPE",
            "SET_EXPLANATION_DENSITY", "SHOW_GUIDANCE",
            "SHOW_DEGRADED_NOTICE", "SUGGEST_NEXT_ACTION",
        ],
    }


def code_hashes() -> dict[str, str]:
    paths = {
        "stage3_executor": "scripts/stage3_background_planning_change_plan.py",
        "planning_policy": "backend/app/agent_workspace/application/background_planning.py",
        "planning_contract": "backend/app/agent_workspace/ports/planning.py",
        "planner_adapter": "backend/app/agent_workspace/adapters/deepseek_planner.py",
        "workspace_runtime": "backend/app/agent_workspace/runtime.py",
        "workspace_api": "backend/app/api/agent_workspaces.py",
        "deepseek_adapter": "backend/app/llm/adapters/deepseek.py",
        "prompt_bundle": "contracts/prompts/background-planning-prompts-v1.json",
    }
    return {key: digest((ROOT / path).read_bytes()) for key, path in paths.items()}


def build_plan(*, run_id: str, env_file: Path) -> tuple[dict[str, Any], dict[str, object]]:
    if RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise ValueError("run id must contain 3-64 safe characters")
    require_clean_worktree()
    settings = load_settings(env_file)
    commit = git_commit()
    fixture = run_dual_workspace_probe(
        model=_FixturePlanningModel(),
        run_id=run_id,
        commit=commit,
        timeout_seconds=5,
    )
    if fixture["external_requests"] != 2:
        raise ValueError("fixture did not exercise exactly two planning calls")
    ids = identities(run_id, commit)
    policy = model_policy(settings)
    context_hashes = {
        str(item["mode"]): str(item["sha256"])
        for item in fixture["model_contexts"]  # type: ignore[union-attr]
    }
    plan: dict[str, Any] = {
        "schema_version": "1.0.0",
        "plan_id": str(uuid5(NAMESPACE_URL, f"stage3-background-plan:{commit}:{run_id}")),
        "created_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "git_commit": commit,
        "classification": "S0_READ_ONLY",
        "mode": "DRY_RUN",
        "intent": (
            "Execute exactly one DeepSeek background-planning attempt for a fixed anonymous "
            "Guest Workspace and exactly one attempt for a fixed formally authenticated reader "
            "Workspace. Validate real HTTP Workspace events, consent-gated sanitized profile "
            "context, directive allowlists and budgets without composing any persistence or "
            "business-write adapter."
        ),
        "environment": {
            "environment_id": "demo-research-stage3-background-planning",
            "workspace": str(ROOT),
            "host_fingerprint": "sha256:" + digest(f"{commit}:{run_id}:stage3".encode()),
            "database_identity": None,
            "index_namespace": None,
        },
        "targets": [
            {
                "kind": "GIT",
                "identifier": f"commit:{commit}",
                "operation": "READ",
                "expected_before_count": 1,
                "expected_after_min_count": 1,
            },
            {
                "kind": "FILE",
                "identifier": PROMPT_PATH.relative_to(ROOT).as_posix(),
                "operation": "READ",
                "expected_before_count": 1,
                "expected_after_min_count": 1,
            },
        ],
        "input_hashes": {
            "identities": digest(canonical(ids)),
            "model_policy": digest(canonical(policy)),
            "guest_context": context_hashes["guest"],
            "authenticated_context": context_hashes["authenticated"],
            **code_hashes(),
        },
        "idempotency_key": str(uuid5(NAMESPACE_URL, f"stage3-background-apply:{commit}:{run_id}")),
        "request_run_id": run_id,
        "max_changes": 0,
        "preconditions": [
            "exact plan_id and canonical plan_hash approval is required",
            "the reviewed Git commit and every bound source hash must remain unchanged",
            "DeepSeek provider and deepseek-v4-flash model are fixed; each Workspace permits one attempt and no retry",
            "the external request ceiling is exactly two: Guest first, authenticated reader second",
            "Guest context contains no profile; reader context contains only consented allow-listed profile summary fields",
            "the model can nominate at most three topic strings; server code owns directive semantics and validation",
            "timeouts, malformed JSON and invalid directives use a model-free rule fallback and remain visibly DEGRADED",
            "no database, Neo4j, Chroma, recommendation, feedback, behavior, audit or Agent tool adapter is composed",
            "database writes, graph/vector writes, business POSTs, destructive actions and deletions remain zero",
        ],
        "safety_assertions": {
            "file_deletions": 0,
            "database_physical_deletions": 0,
            "overwrite_existing": False,
            "destructive_capabilities_required": False,
            "counts_must_not_decrease": True,
        },
    }
    plan["plan_hash"] = digest(canonical(plan))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = list(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(plan)
    )
    if errors:
        raise ValueError(
            "generated ChangePlan violates schema: "
            + "; ".join(error.message for error in errors)
        )
    return plan, fixture


def validate_plan(
    path: Path,
    *,
    plan_id: str,
    plan_hash: str,
    run_id: str,
    env_file: Path,
) -> tuple[dict[str, Any], AppSettings]:
    if HASH_PATTERN.fullmatch(plan_hash) is None:
        raise ValueError("approved plan hash is invalid")
    plan = json.loads(resolve_inside_root(path, label="ChangePlan").read_text(encoding="utf-8"))
    if not isinstance(plan, dict):
        raise ValueError("ChangePlan must be an object")
    unsigned = dict(plan)
    unsigned.pop("plan_hash", None)
    if (
        plan.get("plan_id") != plan_id
        or plan.get("plan_hash") != plan_hash
        or digest(canonical(unsigned)) != plan_hash
    ):
        raise ValueError("approved ChangePlan identity does not match")
    require_clean_worktree()
    commit = git_commit()
    if plan.get("git_commit") != commit or plan.get("request_run_id") != run_id:
        raise ValueError("reviewed commit or run identity changed")
    expected_hashes = code_hashes()
    if any(plan.get("input_hashes", {}).get(key) != value for key, value in expected_hashes.items()):
        raise ValueError("reviewed Stage 3 code changed")
    ids = identities(run_id, commit)
    if plan.get("input_hashes", {}).get("identities") != digest(canonical(ids)):
        raise ValueError("reviewed Stage 3 identities changed")
    settings = load_settings(env_file)
    if plan.get("input_hashes", {}).get("model_policy") != digest(canonical(model_policy(settings))):
        raise ValueError("reviewed DeepSeek policy changed")
    if plan.get("max_changes") != 0 or plan.get("classification") != "S0_READ_ONLY":
        raise ValueError("Stage 3 plan is not read-only")
    return plan, settings


def execute_plan(
    *,
    plan: Mapping[str, Any],
    settings: AppSettings,
    run_id: str,
) -> dict[str, object]:
    bundle = load_prompt_bundle(PROMPT_PATH, expected_version="prompt-v3")
    provider = DeepSeekLLMProvider(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
        max_output_tokens=min(settings.llm_max_output_tokens, 256),
        max_attempts=1,
        prompt_version=bundle.bundle_version,
        prompt_bundle=bundle,
    )
    result = run_dual_workspace_probe(
        model=provider,
        run_id=run_id,
        commit=str(plan["git_commit"]),
        timeout_seconds=settings.llm_timeout_seconds + 3,
    )
    if result["external_requests"] != MAX_EXTERNAL_REQUESTS:
        raise Stage3AcceptanceFailure(
            "STAGE3_EXTERNAL_REQUEST_BUDGET_MISMATCH",
            external_requests=int(result["external_requests"]),
        )
    context_hashes = {
        str(item["mode"]): str(item["sha256"])
        for item in result["model_contexts"]  # type: ignore[union-attr]
    }
    if context_hashes.get("guest") != plan["input_hashes"]["guest_context"]:
        raise Stage3AcceptanceFailure(
            "GUEST_CONTEXT_HASH_CHANGED",
            external_requests=MAX_EXTERNAL_REQUESTS,
        )
    if context_hashes.get("authenticated") != plan["input_hashes"]["authenticated_context"]:
        raise Stage3AcceptanceFailure(
            "AUTHENTICATED_CONTEXT_HASH_CHANGED",
            external_requests=MAX_EXTERNAL_REQUESTS,
        )
    for workspace in result["workspaces"]:  # type: ignore[union-attr]
        if (
            workspace.get("status") != "PLANNED"
            or workspace.get("model_requests") != 1
            or workspace.get("provider") != "deepseek"
            or workspace.get("model") != "deepseek-v4-flash"
            or workspace.get("fallback_used") is not False
            or int(workspace.get("directive_count", 0)) < 1
            or "AGENT_STARTED" not in workspace.get("planning_event_types", [])
            or "AGENT_COMPLETED" not in workspace.get("planning_event_types", [])
        ):
            raise Stage3AcceptanceFailure(
                "WORKSPACE_REAL_PLANNING_ASSERTION_FAILED",
                external_requests=MAX_EXTERNAL_REQUESTS,
                details={
                    "mode": workspace.get("mode"),
                    "status": workspace.get("status"),
                    "reason_code": workspace.get("reason_code"),
                },
            )
    return result


def artifact_dir(run_id: str) -> Path:
    return ROOT / "artifacts/verification/background-planning" / run_id


def _write_json_once(path: Path, value: object) -> None:
    if path.exists():
        raise FileExistsError(f"artifact already exists: {path.name}")
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--run-id", required=True)
    build.add_argument("--llm-env-file", type=Path, default=ROOT / ".env.host")
    apply = subparsers.add_parser("apply")
    apply.add_argument("--apply", action="store_true", required=True)
    apply.add_argument("--run-id", required=True)
    apply.add_argument("--plan", type=Path, required=True)
    apply.add_argument("--plan-id", required=True)
    apply.add_argument("--approved-plan-hash", required=True)
    apply.add_argument("--confirm-external-llm", required=True)
    apply.add_argument("--llm-env-file", type=Path, default=ROOT / ".env.host")
    args = parser.parse_args(argv)
    if RUN_ID_PATTERN.fullmatch(args.run_id) is None:
        print(json.dumps({"status": "FAIL", "reason_code": "INVALID_RUN_ID"}))
        return 1
    try:
        if args.command == "build":
            plan, fixture = build_plan(run_id=args.run_id, env_file=args.llm_env_file)
            output_dir = artifact_dir(args.run_id)
            output_dir.mkdir(parents=True, exist_ok=False)
            _write_json_once(output_dir / "fixture.json", {
                "schema_version": "stage3-background-planning-fixture-v1",
                "status": "PASS",
                "git_commit": plan["git_commit"],
                "external_llm_requests": 0,
                "model_fixture_calls": fixture["external_requests"],
                "result": fixture,
                "database_writes": 0,
                "neo4j_writes": 0,
                "chroma_writes": 0,
                "files_deleted": 0,
                "database_physical_deletions": 0,
            })
            _write_json_once(output_dir / "change-plan.json", plan)
            print(json.dumps({
                "status": "PLAN_PENDING_APPROVAL",
                "plan_id": plan["plan_id"],
                "plan_hash": plan["plan_hash"],
                "maximum_external_requests": MAX_EXTERNAL_REQUESTS,
                "path": str(output_dir / "change-plan.json"),
            }, ensure_ascii=False))
            return 0
        if args.confirm_external_llm != CONFIRMATION:
            raise ValueError("exact external LLM confirmation is required")
        plan, settings = validate_plan(
            args.plan,
            plan_id=args.plan_id,
            plan_hash=args.approved_plan_hash,
            run_id=args.run_id,
            env_file=args.llm_env_file,
        )
        receipt_path = artifact_dir(args.run_id) / "apply.json"
        if receipt_path.exists():
            raise FileExistsError("Stage 3 apply receipt already exists")
        try:
            outcome = execute_plan(
                plan=plan,
                settings=settings,
                run_id=args.run_id,
            )
        except Stage3AcceptanceFailure as exc:
            _write_json_once(receipt_path, {
                "schema_version": "stage3-background-planning-apply-v1",
                "status": "FAIL",
                "plan_id": plan["plan_id"],
                "plan_hash": plan["plan_hash"],
                "git_commit": plan["git_commit"],
                "reason_code": exc.reason_code,
                "details": exc.details,
                "external_llm_requests": exc.external_requests,
                "database_writes": 0,
                "neo4j_writes": 0,
                "chroma_writes": 0,
                "business_posts": 0,
                "files_deleted": 0,
                "database_physical_deletions": 0,
            })
            print(json.dumps({"status": "FAIL", "reason_code": exc.reason_code}))
            return 1
        receipt = {
            "schema_version": "stage3-background-planning-apply-v1",
            "status": "PASS",
            "plan_id": plan["plan_id"],
            "plan_hash": plan["plan_hash"],
            "git_commit": plan["git_commit"],
            "run_id": args.run_id,
            "outcome": outcome,
            "external_llm_requests": MAX_EXTERNAL_REQUESTS,
            "database_writes": 0,
            "neo4j_writes": 0,
            "chroma_writes": 0,
            "business_posts": 0,
            "files_deleted": 0,
            "database_physical_deletions": 0,
            "containers_deleted": 0,
            "volumes_deleted": 0,
        }
        _write_json_once(receipt_path, receipt)
        print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(json.dumps({
            "status": "FAIL",
            "reason_code": "STAGE3_COMMAND_REJECTED",
            "error_type": type(exc).__name__,
        }))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
