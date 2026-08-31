#!/usr/bin/env python3
"""Apply one explicitly approved G4 recommendation projection ChangePlan.

The executor is intentionally fail-closed.  It accepts only a matching
``S1_APPEND``/``DRY_RUN`` plan, an explicit ``--apply`` and the exact plan ID
and hash.  It verifies the reviewed Git commit, both read-only evidence
hashes, the isolated MySQL identity/least-privilege grants, and all table
counts immediately before invoking the opt-in G4 service.  The service owns
one MySQL transaction for the task, Agent facts, candidates, record, items,
policy and trace.  This command never migrates, seeds, updates, deletes, or
writes Neo4j/Chroma.  External DeepSeek Intent/Explanation calls are possible
only when the reviewed plan binds each secret-free policy and every gate is
explicit.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Mapping, Sequence
from uuid import NAMESPACE_URL, UUID, uuid5

import asyncmy
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker

from scripts.g4_projection_contract import (
    validate_g4_projection_request_matches_query_spec,
)
from scripts.g4_llm_plan_policy import (
    load_deepseek_explanation_policy,
    load_deepseek_intent_policy,
    policy_hash,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = PROJECT_ROOT / "contracts" / "safety" / "change-plan.schema.json"
CONFIG_PATH = PROJECT_ROOT / "contracts" / "config" / "examples" / "rec-1.0.0.json"
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
TABLE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")

SHARED_TABLES = (
    "resource_catalog",
    "resource_book_detail",
    "resource_index_state",
    "resource_tag",
    "tag_dictionary",
)
TARGET_TABLES = (
    "recommendation_task",
    "recommendation_task_transition",
    "recommendation_candidate",
    "recommendation_record",
    "recommendation_item",
    "recommendation_item_explanation",
    "recommendation_policy_decision",
    "recommendation_trace",
    "recommendation_agent_message",
    "recommendation_agent_result",
    "recommendation_agent_artifact",
    "recommendation_orchestration_result",
)

GRAPH_VERSION_PATTERN = re.compile(r"^lib-books-v[12]-[0-9]{8}$")
EMBEDDING_VERSION = "hash-char-ngram-v1"
INDEX_VERSION = "lib-books-vector-v1-20260811"
NAMESPACE_NAME = "library_resources__hash_char_ngram_v1"
CHROMA_DIMENSION = 384
EXTERNAL_LLM_CONFIRMATION = "YES_REAL_EXTERNAL_LLM"
DEEPSEEK_PLAN_INTENT = (
    "Prepare one bounded G4 HTTP projection with DeepSeek deepseek-v4-flash "
    "Intent classification for explicit review; no apply is authorized by this plan."
)
DEEPSEEK_EXPLANATION_PLAN_INTENT = (
    "Prepare one bounded G4 HTTP projection with DeepSeek deepseek-v4-flash "
    "Intent classification and evidence-constrained Explanation rendering for explicit "
    "review; no apply is authorized by this plan."
)
DEEPSEEK_PRECONDITIONS = {
    "DeepSeek is capability-scoped to IntentUnderstandingAgent; Explanation remains the evidence template",
    "the only external payload is the frozen non-sensitive request input_text and bounded intent prompt",
    "at most two DeepSeek attempts are authorized and raw provider responses are not persisted",
    "same-request HTTP replay must add zero rows and must not call DeepSeek again",
}
DEEPSEEK_EXPLANATION_PRECONDITIONS = {
    "DeepSeek is capability-scoped to IntentUnderstandingAgent and ExplanationAgent only",
    "Intent receives only frozen non-sensitive input_text; Explanation receives only ranked factors and allowlisted evidence refs",
    "every successful Explanation must use only allowlisted refs and include each used ref as an exact bracketed marker",
    "same-request HTTP replay must add zero rows and must not call DeepSeek again",
}


def canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def resolve_inside_root(value: Path, *, label: str, strict: bool = True) -> Path:
    candidate = value if value.is_absolute() else PROJECT_ROOT / value
    resolved = candidate.resolve(strict=strict)
    try:
        resolved.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError(f"{label} must resolve inside the repository") from exc
    return resolved


def validate_run_id(value: str) -> str:
    if RUN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("run id must use 3-64 safe characters")
    return value


def current_git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    commit = result.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("current git HEAD is not a full commit hash")
    return commit


def load_json(path: Path, *, label: str) -> tuple[dict[str, Any], bytes]:
    resolved = resolve_inside_root(path, label=label)
    raw = resolved.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return payload, raw


def validate_plan(
    path: Path, *, approved_plan_id: str, approved_hash: str
) -> tuple[dict[str, Any], bytes]:
    plan, raw = load_json(path, label="ChangePlan")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = list(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(plan)
    )
    if errors:
        locations = ", ".join(
            ".".join(str(item) for item in error.absolute_path) for error in errors
        )
        raise ValueError(f"ChangePlan violates schema: {locations}")
    if plan.get("classification") != "S1_APPEND" or plan.get("mode") != "DRY_RUN":
        raise ValueError("only an S1_APPEND DRY_RUN ChangePlan may be approved here")
    plan_id = str(plan.get("plan_id"))
    if approved_plan_id != plan_id:
        raise ValueError("approved plan id does not equal the ChangePlan plan_id")
    plan_hash = str(plan.get("plan_hash"))
    if not HASH_PATTERN.fullmatch(approved_hash) or approved_hash != plan_hash:
        raise ValueError("approved hash does not equal the ChangePlan hash")
    unsigned = dict(plan)
    unsigned.pop("plan_hash", None)
    if sha256_bytes(canonical(unsigned)) != plan_hash:
        raise ValueError("ChangePlan hash does not match its canonical contents")
    safety = plan.get("safety_assertions")
    if safety != {
        "file_deletions": 0,
        "database_physical_deletions": 0,
        "overwrite_existing": False,
        "destructive_capabilities_required": False,
        "counts_must_not_decrease": True,
    }:
        raise ValueError("ChangePlan safety assertions are not zero-destructive")
    targets = plan.get("targets")
    if not isinstance(targets, list):
        raise ValueError("ChangePlan targets are not an array")
    target_tables: dict[str, dict[str, Any]] = {}
    for target in targets:
        if not isinstance(target, dict) or target.get("kind") != "MYSQL":
            raise ValueError("ChangePlan contains a non-MySQL target")
        if target.get("operation") != "APPEND":
            raise ValueError("ChangePlan contains a non-append target")
        identifier = str(target.get("identifier", ""))
        table = identifier.rsplit(".", maxsplit=1)[-1]
        if TABLE_PATTERN.fullmatch(table) is None:
            raise ValueError("ChangePlan contains an unsafe table identifier")
        if table in target_tables:
            raise ValueError(f"ChangePlan contains duplicate table target: {table}")
        target_tables[table] = target
    if set(target_tables) != set(TARGET_TABLES):
        raise ValueError("ChangePlan target set does not match the bounded G4 write set")
    expected_total = sum(
        int(target["expected_after_min_count"])
        - int(target["expected_before_count"])
        for target in target_tables.values()
    )
    if int(plan.get("max_changes", -1)) != expected_total:
        raise ValueError(
            "G4 projection ChangePlan max_changes must equal its bounded target deltas"
        )
    if plan_enables_deepseek_explanation(plan):
        if not plan_enables_deepseek_intent(plan):
            raise ValueError("DeepSeek Explanation plan must also bind Intent")
        if plan.get("intent") != DEEPSEEK_EXPLANATION_PLAN_INTENT:
            raise ValueError("DeepSeek Explanation plan intent is not the exact bounded policy")
        preconditions = set(plan.get("preconditions", []))
        if not DEEPSEEK_EXPLANATION_PRECONDITIONS.issubset(preconditions):
            raise ValueError("DeepSeek Explanation plan is missing external-call preconditions")
        request_payload = plan.get("request_payload", {})
        limit = int(request_payload.get("limit", 0)) if isinstance(request_payload, dict) else 0
        expected_attempt_bound = (
            f"at most two Intent attempts plus {limit * 2} Explanation attempts are authorized; "
            "raw provider responses are not persisted"
        )
        expected_concurrency = (
            f"Explanation is bounded to {limit} ranked items with four-way concurrency and "
            "per-item evidence-template fallback"
        )
        if expected_attempt_bound not in preconditions or expected_concurrency not in preconditions:
            raise ValueError("DeepSeek Explanation plan limits do not match the frozen request")
    elif plan_enables_deepseek_intent(plan):
        if plan.get("intent") != DEEPSEEK_PLAN_INTENT:
            raise ValueError("DeepSeek G4 plan intent is not the exact bounded policy")
        if not DEEPSEEK_PRECONDITIONS.issubset(set(plan.get("preconditions", []))):
            raise ValueError("DeepSeek G4 plan is missing external-call preconditions")
    return plan, raw


def plan_enables_deepseek_intent(plan: Mapping[str, Any]) -> bool:
    return "deepseek_intent_policy" in plan.get("input_hashes", {})


def plan_enables_deepseek_explanation(plan: Mapping[str, Any]) -> bool:
    return "deepseek_explanation_policy" in plan.get("input_hashes", {})


def validate_git_boundary(plan: Mapping[str, Any]) -> str:
    reviewed = str(plan["git_commit"])
    current = current_git_commit()
    if current != reviewed:
        raise ValueError(
            "runtime code changed after the reviewed plan commit; regenerate the plan "
            f"(reviewed={reviewed}, current={current})"
        )
    return current


def load_pass_evidence(
    path: Path, *, expected_hash: str, label: str
) -> tuple[dict[str, Any], bytes]:
    evidence, raw = load_json(path, label=label)
    if evidence.get("status") != "PASS":
        raise ValueError(f"{label} must be a PASS object")
    if sha256_bytes(raw) != expected_hash:
        raise ValueError(f"{label} hash does not match the approved plan")
    return evidence, raw


def load_request_payload(
    plan: Mapping[str, Any], *, request_run_id: str
) -> dict[str, Any]:
    """Rebuild the frozen request payload without accepting CLI overrides."""

    if RUN_ID_PATTERN.fullmatch(request_run_id) is None:
        raise ValueError("request run id must use 3-64 safe characters")
    request_id = UUID(str(plan["idempotency_key"]))
    reviewed_run_id = plan.get("request_run_id")
    if reviewed_run_id is not None and str(reviewed_run_id) != request_run_id:
        raise ValueError("request run id does not match the reviewed ChangePlan")
    frozen_payload = plan.get("request_payload")
    if frozen_payload is None:
        expected_request_id = uuid5(
            NAMESPACE_URL, f"g4-recommendation-projection-request:{request_run_id}"
        )
        expected_session_id = uuid5(
            NAMESPACE_URL, f"g4-recommendation-projection-session:{request_run_id}"
        )
        if request_id != expected_request_id:
            raise ValueError("request id does not match the reviewed request run id")
        request_payload = {
            "request_id": str(request_id),
            "session_id": str(expected_session_id),
            "user_id": 1001,
            "scene": "SEARCH_AFTER",
            "input_text": "多智能体系统与智慧图书馆",
            "requested_resource_types": ["BOOK"],
            "requested_output_type": "TOPIC_RESOURCES",
            "limit": 8,
            "g4_channels": ["MYSQL", "GRAPH", "VECTOR"],
        }
    elif isinstance(frozen_payload, Mapping):
        request_payload = dict(frozen_payload)
    else:
        raise ValueError("ChangePlan request_payload must be an object")
    required = {
        "request_id",
        "session_id",
        "user_id",
        "scene",
        "input_text",
        "requested_resource_types",
        "requested_output_type",
        "limit",
        "g4_channels",
    }
    if set(request_payload) != required:
        raise ValueError("ChangePlan request_payload fields are not frozen")
    if UUID(str(request_payload["request_id"])) != request_id:
        raise ValueError("request_payload.request_id does not match idempotency_key")
    try:
        UUID(str(request_payload["session_id"]))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("request_payload.session_id must be a UUID") from exc
    if int(request_payload["user_id"]) < 1:
        raise ValueError("request_payload user_id must be positive")
    if request_payload["scene"] != "SEARCH_AFTER":
        raise ValueError("request_payload scene is not SEARCH_AFTER")
    if request_payload["requested_resource_types"] != ["BOOK"]:
        raise ValueError("request_payload resource types are not the approved BOOK set")
    output_type = request_payload["requested_output_type"]
    if output_type not in {"TOPIC_RESOURCES", "READING_PATH"}:
        raise ValueError("request_payload output type is not approved")
    if request_payload["g4_channels"] != ["MYSQL", "GRAPH", "VECTOR"]:
        raise ValueError("request_payload G4 channels are not the approved set")
    if not isinstance(request_payload["input_text"], str) or not request_payload["input_text"].strip():
        raise ValueError("request_payload input_text must be non-blank")
    minimum_limit = 6 if output_type == "READING_PATH" else 1
    if isinstance(request_payload["limit"], bool) or not minimum_limit <= int(request_payload["limit"]) <= 20:
        raise ValueError("request_payload limit is outside the approved output-type bounds")
    if sha256_bytes(canonical(request_payload)) != str(
        plan["input_hashes"]["request_payload"]
    ):
        raise ValueError("reconstructed request payload hash does not match the plan")
    if int(request_payload["user_id"]) < 1:
        raise ValueError("request_payload user_id must be positive")
    if not isinstance(request_payload["requested_resource_types"], list) or not request_payload[
        "requested_resource_types"
    ]:
        raise ValueError("request_payload resource types must be a non-empty list")
    if request_payload["g4_channels"] != ["MYSQL", "GRAPH", "VECTOR"]:
        raise ValueError("request_payload G4 channels are not the approved set")
    return request_payload


def load_approved_graph_runtime(
    g4_baseline: Mapping[str, Any],
    values: Mapping[str, str],
    graph_values: Mapping[str, str],
) -> tuple[str, str, str, str, str]:
    """Resolve the graph version and isolated read-only endpoint from evidence.

    The G4 evidence is hash-bound by the ChangePlan, so the selected graph
    version cannot be changed by a runtime environment override.  The final
    Neo4j replica uses a separate env file and the built-in ``neo4j`` account;
    administrator credentials are deliberately not accepted for this path.
    """

    versions = g4_baseline.get("versions")
    graph_version = versions.get("graph_version") if isinstance(versions, Mapping) else None
    if (
        not isinstance(graph_version, str)
        or GRAPH_VERSION_PATTERN.fullmatch(graph_version) is None
    ):
        raise ValueError("approved G4 evidence does not contain a safe graph version")

    final_port = graph_values.get("RECPRO_FINAL_NEO4J_HTTP_HOST_PORT")
    final_password = graph_values.get("RECPRO_FINAL_NEO4J_PASSWORD")
    if final_port and final_password:
        graph_endpoint_port = final_port
        graph_username = graph_values.get("RECPRO_FINAL_NEO4J_USER", "neo4j")
        graph_password = final_password
        graph_source = "final-readonly-replica"
    else:
        # A future operator-provided read-only env may use the normalized
        # names.  Never fall back to RECPRO_NEO4J_ADMIN_* here.
        graph_endpoint_port = graph_values.get(
            "RECPRO_LIBRARY_NEO4J_HTTP_HOST_PORT",
            values.get("RECPRO_LIBRARY_NEO4J_HTTP_HOST_PORT", ""),
        )
        graph_username = graph_values.get(
            "RECPRO_NEO4J_READ_USER", values.get("RECPRO_NEO4J_READ_USER", "")
        )
        graph_password = graph_values.get(
            "RECPRO_NEO4J_READ_PASSWORD", values.get("RECPRO_NEO4J_READ_PASSWORD", "")
        )
        graph_source = "configured-readonly-endpoint"
    if not graph_endpoint_port or not graph_username or not graph_password:
        raise ValueError(
            "approved G4 projection requires an explicit Neo4j read-only endpoint and credentials"
        )
    try:
        port = int(graph_endpoint_port)
    except (TypeError, ValueError) as exc:
        raise ValueError("Neo4j read-only HTTP port is invalid") from exc
    if not 1 <= port <= 65535:
        raise ValueError("Neo4j read-only HTTP port is out of range")
    return graph_version, str(port), graph_username, graph_password, graph_source


async def read_table_counts(values: Mapping[str, str]) -> tuple[tuple[str, ...], dict[str, int]]:
    connection = await asyncmy.connect(
        host="127.0.0.1",
        port=int(values["RECPRO_MYSQL_HOST_PORT"]),
        user=values["RECPRO_MYSQL_USER"],
        password=values["RECPRO_MYSQL_PASSWORD"],
        db=values["RECPRO_MYSQL_DATABASE"],
        connect_timeout=10,
        read_timeout=60,
        charset="utf8mb4",
        autocommit=True,
    )
    try:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = DATABASE() ORDER BY table_name"
            )
            table_names = tuple(str(row[0]) for row in await cursor.fetchall())
            if any(TABLE_PATTERN.fullmatch(table) is None for table in table_names):
                raise RuntimeError("database returned an unsafe table identifier")
            counts: dict[str, int] = {}
            for table in table_names:
                await cursor.execute(f"SELECT COUNT(*) FROM `{table}`")
                row = await cursor.fetchone()
                if row is None:
                    raise RuntimeError(f"count query returned no row for {table}")
                counts[table] = int(row[0])
        return table_names, counts
    finally:
        connection.close()


async def read_database_guard(
    values: Mapping[str, str], *, request_id: UUID, user_id: int
) -> dict[str, Any]:
    from backend.app.observability.adapters.mysql_readiness import GrantSafetyEvaluator

    connection = await asyncmy.connect(
        host="127.0.0.1",
        port=int(values["RECPRO_MYSQL_HOST_PORT"]),
        user=values["RECPRO_MYSQL_USER"],
        password=values["RECPRO_MYSQL_PASSWORD"],
        db=values["RECPRO_MYSQL_DATABASE"],
        connect_timeout=10,
        read_timeout=30,
        charset="utf8mb4",
        autocommit=True,
    )
    try:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT probe_id, DATABASE(), CURRENT_USER(), "
                "@@character_set_database, @@character_set_connection "
                "FROM recpro_runtime_probe WHERE probe_id = %s",
                (values["RECPRO_PERSISTENCE_PROBE_ID"],),
            )
            identity = await cursor.fetchone()
            if (
                identity is None
                or identity[0] != values["RECPRO_PERSISTENCE_PROBE_ID"]
                or identity[1] != values["RECPRO_MYSQL_DATABASE"]
                or str(identity[2]).split("@", maxsplit=1)[0]
                != values["RECPRO_MYSQL_USER"]
                or identity[3] != "utf8mb4"
                or identity[4] != "utf8mb4"
            ):
                raise RuntimeError("database identity or runtime probe does not match the plan")
            await cursor.execute("SHOW GRANTS")
            grants = tuple(str(row[0]) for row in await cursor.fetchall() if row)
            if not GrantSafetyEvaluator(values["RECPRO_MYSQL_DATABASE"]).grants_are_safe(grants):
                raise RuntimeError("runtime grants failed the least-privilege guard")
            await cursor.execute(
                "SELECT id FROM recommendation_task "
                "WHERE request_id = %s AND user_id = %s LIMIT 1",
                (str(request_id), user_id),
            )
            existing = await cursor.fetchone()
            if existing is not None:
                raise RuntimeError("approved request_id already exists; refusing replay/apply")
        return {
            "probe_id": values["RECPRO_PERSISTENCE_PROBE_ID"],
            "current_user": str(identity[2]),
            "grants_safe": True,
            "existing_request": False,
        }
    finally:
        connection.close()


def validate_pre_counts(
    *, plan: Mapping[str, Any], before_counts: Mapping[str, int],
    mysql_baseline: Mapping[str, Any], g4_baseline: Mapping[str, Any]
) -> None:
    target_by_table = {
        str(target["identifier"]).rsplit(".", maxsplit=1)[-1]: target
        for target in plan["targets"]
    }
    for table in TARGET_TABLES:
        expected = int(target_by_table[table]["expected_before_count"])
        actual = int(before_counts.get(table, -1))
        if actual != expected:
            raise RuntimeError(f"pre-count drift for {table}: {actual} != {expected}")
    mysql_counts = mysql_baseline.get("before_counts", {})
    g4_counts = g4_baseline.get("before_counts", {})
    for table in SHARED_TABLES:
        expected = int(mysql_counts[table])
        if int(g4_counts[table]) != expected:
            raise RuntimeError(f"baseline shared count differs for {table}")
        if int(before_counts.get(table, -1)) != expected:
            raise RuntimeError(f"shared pre-count drift for {table}")


def validate_post_counts(
    *,
    plan: Mapping[str, Any],
    before_table_names: Sequence[str],
    before_counts: Mapping[str, int],
    after_table_names: Sequence[str],
    after_counts: Mapping[str, int],
) -> dict[str, int]:
    if tuple(before_table_names) != tuple(after_table_names):
        raise RuntimeError("database table set changed during the approved append")
    deltas = {
        table: int(after_counts[table]) - int(before_counts[table])
        for table in before_table_names
    }
    if any(value < 0 for value in deltas.values()):
        raise RuntimeError(f"a table count decreased: {deltas}")
    target_by_table = {
        str(target["identifier"]).rsplit(".", maxsplit=1)[-1]: target
        for target in plan["targets"]
    }
    for table in SHARED_TABLES:
        if deltas.get(table) != 0:
            raise RuntimeError(f"protected shared table changed: {table}={deltas[table]}")
    for table in before_table_names:
        if table in SHARED_TABLES or table in TARGET_TABLES:
            continue
        if deltas[table] != 0:
            raise RuntimeError(f"unplanned table changed: {table}={deltas[table]}")
    for table in TARGET_TABLES:
        target = target_by_table[table]
        expected = int(target["expected_after_min_count"]) - int(
            target["expected_before_count"]
        )
        if deltas.get(table) != expected:
            raise RuntimeError(
                f"planned delta mismatch for {table}: {deltas.get(table)} != {expected}"
            )
    if sum(deltas[table] for table in TARGET_TABLES) > int(plan["max_changes"]):
        raise RuntimeError("actual append rows exceeded ChangePlan max_changes")
    return {table: deltas[table] for table in TARGET_TABLES}


def build_settings(
    values: Mapping[str, str],
    *,
    enable_deepseek_intent: bool,
    enable_deepseek_explanation: bool = False,
    llm_settings: Any | None = None,
):
    from backend.app.config import AppSettings

    return AppSettings(
        app_env="demo",
        app_version="0.1.0",
        config_bundle_path=values["RECPRO_CONFIG_BUNDLE_PATH"],
        config_bundle_sha256=values["RECPRO_CONFIG_BUNDLE_SHA256"],
        config_bundle_version=values["RECPRO_CONFIG_BUNDLE_VERSION"],
        prompt_bundle_path=values.get(
            "RECPRO_PROMPT_BUNDLE_PATH", "contracts/prompts/rec-prompts-v1.0.1.json"
        ),
        prompt_bundle_sha256=values.get(
            "RECPRO_PROMPT_BUNDLE_SHA256",
            "1fa3b19788574189ae1680a0ef5565fd378200d146d9c0ba83da583ba3abce1a",
        ),
        prompt_bundle_version=values.get("RECPRO_PROMPT_BUNDLE_VERSION", "prompt-v1"),
        mysql_host="127.0.0.1",
        mysql_port=int(values["RECPRO_MYSQL_HOST_PORT"]),
        mysql_database=values["RECPRO_MYSQL_DATABASE"],
        mysql_user=values["RECPRO_MYSQL_USER"],
        mysql_password=values["RECPRO_MYSQL_PASSWORD"],
        mysql_connect_timeout_seconds=float(
            values.get("RECPRO_MYSQL_CONNECT_TIMEOUT_SECONDS", "3")
        ),
        persistence_probe_id=values["RECPRO_PERSISTENCE_PROBE_ID"],
        llm_provider=(llm_settings.llm_provider if enable_deepseek_intent else "mock"),
        llm_base_url=(
            llm_settings.llm_base_url
            if enable_deepseek_intent
            else "https://api.deepseek.com"
        ),
        llm_model=(
            llm_settings.llm_model if enable_deepseek_intent else "deepseek-v4-flash"
        ),
        llm_api_key=(llm_settings.llm_api_key if enable_deepseek_intent else None),
        llm_timeout_seconds=(
            llm_settings.llm_timeout_seconds if enable_deepseek_intent else 20.0
        ),
        llm_max_output_tokens=(
            llm_settings.llm_max_output_tokens if enable_deepseek_intent else 512
        ),
        g4_http_enabled=True,
        g4_llm_intent_enabled=enable_deepseek_intent,
        g4_llm_explanation_enabled=enable_deepseek_explanation,
    )


async def read_intent_llm_receipt(
    values: Mapping[str, str], *, task_id: str
) -> dict[str, Any]:
    connection = await asyncmy.connect(
        host="127.0.0.1",
        port=int(values["RECPRO_MYSQL_HOST_PORT"]),
        user=values["RECPRO_MYSQL_USER"],
        password=values["RECPRO_MYSQL_PASSWORD"],
        db=values["RECPRO_MYSQL_DATABASE"],
        connect_timeout=10,
        read_timeout=30,
        charset="utf8mb4",
        autocommit=True,
    )
    try:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT agent_version, fallback_used, payload_json "
                "FROM recommendation_agent_result "
                "WHERE task_id = %s AND context_version = 1 "
                "AND agent_name = 'IntentUnderstandingAgent'",
                (task_id,),
            )
            rows = await cursor.fetchall()
        if len(rows) != 1:
            raise RuntimeError("persisted task does not have exactly one Intent Agent result")
        payload = rows[0][2]
        if isinstance(payload, (bytes, bytearray)):
            payload = payload.decode("utf-8")
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, dict):
            raise RuntimeError("persisted Intent Agent payload is invalid")
        return {
            "agent_version": str(rows[0][0]),
            "fallback_used": bool(rows[0][1]),
            "llm_provider": payload.get("llm_provider"),
            "prompt_version": payload.get("prompt_version"),
            "prompt_id": payload.get("prompt_id"),
            "prompt_sha256": payload.get("prompt_sha256"),
            "llm_attempts": int(payload.get("llm_attempts", 0)),
            "intent_type": payload.get("intent_type"),
        }
    finally:
        connection.close()


async def read_explanation_llm_receipt(
    values: Mapping[str, str], *, task_id: str, expected_items: int
) -> dict[str, Any]:
    connection = await asyncmy.connect(
        host="127.0.0.1",
        port=int(values["RECPRO_MYSQL_HOST_PORT"]),
        user=values["RECPRO_MYSQL_USER"],
        password=values["RECPRO_MYSQL_PASSWORD"],
        db=values["RECPRO_MYSQL_DATABASE"],
        connect_timeout=10,
        read_timeout=30,
        charset="utf8mb4",
        autocommit=True,
    )
    try:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT agent_version, fallback_used, payload_json "
                "FROM recommendation_agent_result "
                "WHERE task_id = %s AND context_version = 1 "
                "AND agent_name = 'ExplanationAgent'",
                (task_id,),
            )
            rows = await cursor.fetchall()
        if len(rows) != 1:
            raise RuntimeError("persisted task does not have exactly one Explanation Agent result")
        payload = rows[0][2]
        if isinstance(payload, (bytes, bytearray)):
            payload = payload.decode("utf-8")
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, dict):
            raise RuntimeError("persisted Explanation Agent payload is invalid")
        explanations = payload.get("explanations")
        if not isinstance(explanations, list) or len(explanations) != expected_items:
            raise RuntimeError("persisted Explanation count does not match ranked items")
        validated_refs = 0
        fallback_used = bool(rows[0][1])
        for explanation in explanations:
            if not isinstance(explanation, dict):
                raise RuntimeError("persisted Explanation entry is invalid")
            summary = explanation.get("summary")
            refs = explanation.get("evidence_refs")
            if not isinstance(summary, str) or not summary.strip() or len(summary.strip()) > 240:
                raise RuntimeError("persisted Explanation text is invalid")
            if not isinstance(refs, list) or not refs:
                raise RuntimeError("persisted Explanation omitted evidence refs")
            for reference in refs:
                if not isinstance(reference, str):
                    raise RuntimeError("persisted Explanation contains an invalid evidence ref")
                if not fallback_used and f"[{reference}]" not in summary:
                    raise RuntimeError("persisted Explanation omitted an exact evidence marker")
                validated_refs += 1
        return {
            "agent_version": str(rows[0][0]),
            "fallback_used": fallback_used,
            "provider": payload.get("provider"),
            "llm_attempts": int(payload.get("llm_attempts", 0)),
            "explanation_count": len(explanations),
            "validated_evidence_ref_count": validated_refs,
            "evidence_markers_valid": not fallback_used,
        }
    finally:
        connection.close()


def load_chroma(site_packages: Path):
    resolved = site_packages.resolve(strict=True)
    if str(resolved) not in sys.path:
        sys.path.insert(0, str(resolved))
    try:
        import chromadb
    except ModuleNotFoundError as exc:
        raise RuntimeError("chromadb operator dependency is unavailable") from exc
    return chromadb


async def execute(args: argparse.Namespace) -> dict[str, Any]:
    if not args.apply:
        raise ValueError("--apply is required; omission is fail-closed")
    run_id = validate_run_id(args.run_id)
    if args.plan_id is None or args.approved_plan_hash is None:
        raise ValueError("--plan-id and --approved-plan-hash are required")
    plan, plan_raw = validate_plan(
        args.plan,
        approved_plan_id=args.plan_id,
        approved_hash=args.approved_plan_hash,
    )
    enable_deepseek_intent = plan_enables_deepseek_intent(plan)
    enable_deepseek_explanation = plan_enables_deepseek_explanation(plan)
    if enable_deepseek_intent != bool(args.enable_deepseek_intent):
        raise ValueError("CLI DeepSeek Intent gate does not match the approved plan")
    if enable_deepseek_explanation != bool(args.enable_deepseek_explanation):
        raise ValueError("CLI DeepSeek Explanation gate does not match the approved plan")
    if enable_deepseek_intent and args.confirm_external_llm != EXTERNAL_LLM_CONFIRMATION:
        raise ValueError("exact external LLM confirmation is required")
    if not enable_deepseek_intent and args.confirm_external_llm:
        raise ValueError("external LLM confirmation was supplied for a Mock-only plan")
    llm_settings = None
    llm_policy = None
    explanation_policy = None
    if enable_deepseek_intent:
        llm_settings, llm_policy = load_deepseek_intent_policy(args.llm_env_file)
        if policy_hash(llm_policy) != plan["input_hashes"]["deepseek_intent_policy"]:
            raise ValueError("local DeepSeek Intent policy differs from the approved plan")
    if enable_deepseek_explanation:
        llm_settings, explanation_policy = load_deepseek_explanation_policy(
            args.llm_env_file, max_items=int(plan["request_payload"]["limit"])
        )
        if (
            policy_hash(explanation_policy)
            != plan["input_hashes"]["deepseek_explanation_policy"]
        ):
            raise ValueError("local DeepSeek Explanation policy differs from the approved plan")
    current_commit = validate_git_boundary(plan)
    mysql_baseline, mysql_baseline_raw = load_pass_evidence(
        args.mysql_baseline,
        expected_hash=str(plan["input_hashes"]["mysql_baseline_readonly_evidence"]),
        label="MySQL baseline evidence",
    )
    g4_baseline, g4_baseline_raw = load_pass_evidence(
        args.g4_baseline,
        expected_hash=str(plan["input_hashes"]["g4_baseline_readonly_evidence"]),
        label="G4 baseline evidence",
    )
    if g4_baseline.get("candidate_enrichment") != {
        "channel_scores": True,
        "channel_ranks": True,
        "primary_channel": True,
        "evidence_confidence": True,
    }:
        raise ValueError("G4 baseline does not prove candidate enrichment")
    target_candidate_delta = next(
        int(target["expected_after_min_count"])
        - int(target["expected_before_count"])
        for target in plan["targets"]
        if str(target["identifier"]).rsplit(".", maxsplit=1)[-1]
        == "recommendation_candidate"
    )
    if int(g4_baseline.get("candidate_persistence_rows", -1)) != target_candidate_delta:
        raise ValueError("G4 baseline candidate row count does not match the plan")
    if sha256_bytes(CONFIG_PATH.read_bytes()) != plan["input_hashes"]["config_bundle"]:
        raise ValueError("config bundle hash does not match the approved plan")
    request_payload = load_request_payload(plan, request_run_id=args.request_run_id)
    validate_g4_projection_request_matches_query_spec(
        g4_baseline.get("query_spec"),
        input_text=str(request_payload["input_text"]),
        resource_types=list(request_payload["requested_resource_types"]),
        output_type=str(request_payload["requested_output_type"]),
        limit=int(request_payload["limit"]),
    )

    from scripts.validate_runtime_env import read_env, validate_compose

    compose_values = read_env(args.env_file.resolve())
    issues = validate_compose(compose_values)
    if issues:
        raise ValueError("runtime environment failed safe preflight: " + "; ".join(issues))
    secret_values = read_env(args.secrets_file.resolve())
    values = {**compose_values, **secret_values}
    graph_values = read_env(args.graph_env_file.resolve())
    required = (
        "RECPRO_MYSQL_HOST_PORT",
        "RECPRO_MYSQL_DATABASE",
        "RECPRO_MYSQL_USER",
        "RECPRO_MYSQL_PASSWORD",
    )
    missing = [key for key in required if not values.get(key)]
    if missing:
        raise ValueError(f"missing required runtime keys: {missing}")
    graph_version, graph_port, graph_username, graph_password, graph_source = load_approved_graph_runtime(
        g4_baseline, values, graph_values
    )
    configured_llm_provider = llm_settings.llm_provider if enable_deepseek_intent else "mock"
    if values["COMPOSE_PROJECT_NAME"] != plan["environment"]["environment_id"]:
        raise ValueError("Compose project does not match the approved plan")
    database_identity = (
        f"mysql://{values['COMPOSE_PROJECT_NAME']}/{values['RECPRO_MYSQL_DATABASE']}"
    )
    if database_identity != plan["environment"]["database_identity"]:
        raise ValueError("MySQL database identity does not match the approved plan")
    host_fingerprint = "sha256:" + sha256_bytes(
        f"{values['COMPOSE_PROJECT_NAME']}:{values['RECPRO_MYSQL_DATABASE']}:{PROJECT_ROOT}:{current_commit}".encode(
            "utf-8"
        )
    )
    if host_fingerprint != plan["environment"]["host_fingerprint"]:
        raise ValueError("host fingerprint does not match the approved plan")

    request_id = UUID(str(plan["idempotency_key"]))
    user_id = int(request_payload["user_id"])
    guard = await read_database_guard(values, request_id=request_id, user_id=user_id)
    before_table_names, before_counts = await read_table_counts(values)
    validate_pre_counts(
        plan=plan,
        before_counts=before_counts,
        mysql_baseline=mysql_baseline,
        g4_baseline=g4_baseline,
    )
    if sha256_bytes(mysql_baseline_raw) != plan["input_hashes"]["mysql_baseline_readonly_evidence"]:
        raise ValueError("MySQL baseline hash changed during preflight")
    if sha256_bytes(g4_baseline_raw) != plan["input_hashes"]["g4_baseline_readonly_evidence"]:
        raise ValueError("G4 baseline hash changed during preflight")

    chromadb = load_chroma(args.chroma_site_packages.resolve())
    chroma_path = args.chroma_path.resolve(strict=True)
    if not chroma_path.is_dir():
        raise ValueError("Chroma path must be an existing directory")
    chroma_client = chromadb.PersistentClient(path=str(chroma_path))
    collection = chroma_client.get_collection(NAMESPACE_NAME, embedding_function=None)
    chroma_before = int(collection.count())
    if chroma_before <= 0:
        raise ValueError("approved Chroma collection is empty")

    from backend.app.catalog.adapters.chroma import ChromaVectorReader
    from backend.app.catalog.adapters.embedding import HashCharNgramQueryEmbedder
    from backend.app.catalog.adapters.neo4j import Neo4jGraphReader
    from backend.app.composition import (
        build_research_g4_http_app,
        build_research_g4_recommendation_service,
    )

    graph = Neo4jGraphReader(
        endpoint=(
            f"http://127.0.0.1:{graph_port}"
            "/db/neo4j/tx/commit"
        ),
        username=graph_username,
        password=graph_password,
        timeout=8,
    )
    vector = ChromaVectorReader(
        collection=collection,
        namespace_name=NAMESPACE_NAME,
        embedding_version=EMBEDDING_VERSION,
        index_version=INDEX_VERSION,
        dimension=CHROMA_DIMENSION,
        timeout=8,
    )
    settings = build_settings(
        values,
        enable_deepseek_intent=enable_deepseek_intent,
        enable_deepseek_explanation=enable_deepseek_explanation,
        llm_settings=llm_settings,
    )
    service = build_research_g4_recommendation_service(
        settings,
        dataset_version="lib-books-v1-20260810",
        graph=graph,
        graph_version=graph_version,
        vector=vector,
        query_embedder=HashCharNgramQueryEmbedder(),
        embedding_version=EMBEDDING_VERSION,
        index_version=INDEX_VERSION,
        enable_llm_provider=False,
        enable_llm_intent_provider=enable_deepseek_intent,
        enable_llm_explanation_provider=enable_deepseek_explanation,
        deadline_seconds=120.0,
    )
    application = build_research_g4_http_app(
        settings,
        recommendation_service=service,
    )
    http_payload = {
        "request_id": str(request_id),
        "session_id": str(request_payload["session_id"]),
        "user_id": user_id,
        "scene": str(request_payload["scene"]),
        "input_text": str(request_payload["input_text"]),
        "requested_resource_types": list(request_payload["requested_resource_types"]),
        "requested_output_type": str(request_payload["requested_output_type"]),
        "source_resource_id": None,
        "source_item_id": None,
        "as_of_time": None,
        "constraints": {},
        "limit": int(request_payload["limit"]),
    }
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Idempotency-Key": str(request_id),
        "X-Demo-User-Id": str(user_id),
    }
    with TestClient(application) as client:
        live = client.get("/api/v1/health/live")
        ready = client.get("/api/v1/health/ready")
        if live.status_code != 200 or ready.status_code != 200:
            raise RuntimeError(
                f"G4 HTTP health gate failed: live={live.status_code}, ready={ready.status_code}"
            )
        if ready.json().get("can_recommend") is not True:
            raise RuntimeError("G4 HTTP health gate did not enable recommendation")
        response = client.post(
            "/api/v1/recommendation-tasks", json=http_payload, headers=headers
        )
        if response.status_code != 201:
            raise RuntimeError(
                f"approved G4 HTTP POST returned {response.status_code}: {response.text[:400]}"
            )
        if response.headers.get("Idempotency-Replayed") != "false":
            raise RuntimeError("approved G4 HTTP POST was unexpectedly replayed")
        payload = dict(response.json())
        after_first_table_names, after_first_counts = await read_table_counts(values)
        replay = client.post(
            "/api/v1/recommendation-tasks", json=http_payload, headers=headers
        )
        after_replay_table_names, after_replay_counts = await read_table_counts(values)
        if replay.status_code != 200:
            raise RuntimeError(f"G4 HTTP replay returned {replay.status_code}")
        if replay.headers.get("Idempotency-Replayed") != "true":
            raise RuntimeError("G4 HTTP replay was not marked as replayed")
        if replay.json().get("task_id") != payload.get("task_id"):
            raise RuntimeError("G4 HTTP replay returned a different task")
        if (
            after_replay_table_names != after_first_table_names
            or after_replay_counts != after_first_counts
        ):
            raise RuntimeError("G4 HTTP replay changed database counts")
        persisted = client.get(
            f"/api/v1/recommendation-tasks/{payload.get('task_id')}",
            headers={"X-Demo-User-Id": str(user_id)},
        )
        if persisted.status_code != 200:
            raise RuntimeError(f"G4 persisted task GET returned {persisted.status_code}")
    if payload.get("status") not in {"COMPLETED", "DEGRADED_COMPLETED"}:
        raise RuntimeError(f"approved G4 projection did not complete: {payload.get('status')!r}")
    if not payload.get("record_id"):
        raise RuntimeError("approved G4 projection response has no record_id")
    after_table_names, after_counts = await read_table_counts(values)
    deltas = validate_post_counts(
        plan=plan,
        before_table_names=before_table_names,
        before_counts=before_counts,
        after_table_names=after_table_names,
        after_counts=after_counts,
    )
    chroma_after = int(collection.count())
    if chroma_after != chroma_before:
        raise RuntimeError("Chroma count changed during G4 projection")
    intent_receipt = await read_intent_llm_receipt(
        values, task_id=str(payload["task_id"])
    )
    if enable_deepseek_intent:
        if intent_receipt["agent_version"] != "intent-llm-prompt-v1":
            raise RuntimeError("G4 HTTP task did not persist the LLM Intent Agent")
        if intent_receipt["fallback_used"]:
            raise RuntimeError("G4 HTTP DeepSeek Intent unexpectedly fell back")
        if intent_receipt["llm_provider"] != "deepseek":
            raise RuntimeError("G4 HTTP Intent receipt is not from DeepSeek")
        if intent_receipt["prompt_id"] != "intent.classify":
            raise RuntimeError("G4 HTTP Intent receipt has the wrong prompt")
        if not 1 <= intent_receipt["llm_attempts"] <= 2:
            raise RuntimeError("G4 HTTP Intent attempts exceed the approved bound")
    item_count = len(payload.get("items", [])) if isinstance(payload.get("items"), list) else 0
    explanation_receipt: dict[str, Any] = {
        "enabled": False,
        "llm_attempts": 0,
        "explanation_count": item_count,
    }
    if enable_deepseek_explanation:
        explanation_receipt = await read_explanation_llm_receipt(
            values,
            task_id=str(payload["task_id"]),
            expected_items=item_count,
        )
        explanation_receipt["enabled"] = True
        if explanation_receipt["fallback_used"]:
            if explanation_receipt["agent_version"] != "explanation-template-fallback-v1":
                raise RuntimeError("G4 HTTP Explanation fallback has an unexpected agent version")
            if explanation_receipt["provider"] != "TEMPLATE":
                raise RuntimeError("G4 HTTP Explanation fallback has an unexpected provider")
        elif explanation_receipt["agent_version"] != "explanation-llm-prompt-v1":
            raise RuntimeError("G4 HTTP task did not persist the LLM Explanation Agent")
        elif explanation_receipt["provider"] != "DEEPSEEK":
            raise RuntimeError("G4 HTTP Explanation receipt is not from DeepSeek")
        if not 0 <= explanation_receipt["llm_attempts"] <= item_count * 2:
            raise RuntimeError("G4 HTTP Explanation attempts exceed the approved bound")

    evidence_dir = PROJECT_ROOT / "artifacts" / "verification" / "g4" / run_id
    if evidence_dir.exists():
        raise FileExistsError(f"evidence directory already exists: {evidence_dir}")
    evidence = {
        "schema_version": "g4-recommendation-projection-approved-append-v1",
        "status": "PASS",
        "run_id": run_id,
        "approved_plan_id": args.plan_id,
        "approved_plan_hash": args.approved_plan_hash,
        "plan_path": str(resolve_inside_root(args.plan, label="ChangePlan")),
        "plan_git_commit": plan["git_commit"],
        "current_git_commit": current_commit,
        "mysql_baseline_path": str(
            resolve_inside_root(args.mysql_baseline, label="MySQL baseline evidence")
        ),
        "g4_baseline_path": str(
            resolve_inside_root(args.g4_baseline, label="G4 baseline evidence")
        ),
        "compose_project": values["COMPOSE_PROJECT_NAME"],
        "mysql_host": "127.0.0.1",
        "mysql_port": int(values["RECPRO_MYSQL_HOST_PORT"]),
        "request_id": str(request_id),
        "session_id": str(request_payload["session_id"]),
        "user_id": user_id,
        "database_guard": guard,
        "before_counts": before_counts,
        "after_counts": after_counts,
        "deltas": deltas,
        "chroma_count_before": chroma_before,
        "chroma_count_after": chroma_after,
        "response_summary": {
            "status_code": response.status_code,
            "replayed": response.headers.get("Idempotency-Replayed") == "true",
            "task_id": payload.get("task_id"),
            "trace_id": payload.get("trace_id"),
            "status": payload.get("status"),
            "context_version": payload.get("context_version"),
            "record_id": payload.get("record_id"),
            "item_count": len(payload.get("items", []))
            if isinstance(payload.get("items"), list)
                else None,
        },
        "replay_summary": {
            "status_code": replay.status_code,
            "idempotency_replayed": replay.headers.get("Idempotency-Replayed"),
            "same_task_identity": replay.json().get("task_id") == payload.get("task_id"),
            "zero_additional_row_delta": True,
        },
        "http": {
            "business_posts": 2,
            "business_gets": 1,
            "live_status_code": live.status_code,
            "ready_status_code": ready.status_code,
            "can_recommend": ready.json().get("can_recommend"),
        },
        "intent_agent": intent_receipt,
        "explanation_agent": explanation_receipt,
        "mode": "APPLY_ONE_BOUNDED_HTTP_APPEND_AND_EXACT_REPLAY",
        "database_write_rows": sum(deltas.values()),
        "database_writes": sum(deltas.values()),
        "external_requests": intent_receipt["llm_attempts"]
        + (explanation_receipt["llm_attempts"] if enable_deepseek_explanation else 0),
        "external_llm_requests": intent_receipt["llm_attempts"]
        + (explanation_receipt["llm_attempts"] if enable_deepseek_explanation else 0),
        "configured_llm_provider": configured_llm_provider,
        "graph_version": graph_version,
        "graph_source": graph_source,
        "graph_writes": 0,
        "neo4j_writes": 0,
        "chroma_writes": 0,
        "actual_delete_count": 0,
        "files_deleted": 0,
        "overwritten_inputs": 0,
        "max_changes": int(plan["max_changes"]),
        "plan_raw_sha256": sha256_bytes(plan_raw),
    }
    evidence_dir.mkdir(parents=True, exist_ok=False)
    (evidence_dir / "g4-recommendation-projection-apply.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return evidence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--plan-id", required=True)
    parser.add_argument("--approved-plan-hash", required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--mysql-baseline", type=Path, required=True)
    parser.add_argument("--g4-baseline", type=Path, required=True)
    parser.add_argument("--request-run-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.compose")
    parser.add_argument("--secrets-file", type=Path, default=PROJECT_ROOT / ".env.user-secrets")
    parser.add_argument(
        "--graph-env-file",
        type=Path,
        default=PROJECT_ROOT / ".env.neo4j-readonly-final.local",
    )
    parser.add_argument("--enable-deepseek-intent", action="store_true")
    parser.add_argument("--enable-deepseek-explanation", action="store_true")
    parser.add_argument("--confirm-external-llm")
    parser.add_argument("--llm-env-file", type=Path, default=PROJECT_ROOT / ".env.host")
    parser.add_argument("--chroma-path", type=Path, default=PROJECT_ROOT / "data" / "chroma")
    parser.add_argument(
        "--chroma-site-packages",
        type=Path,
        default=PROJECT_ROOT / ".venv-chroma-g6-20260811" / "lib" / "python3.11" / "site-packages",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        evidence = asyncio.run(execute(args))
    except (
        OSError,
        RuntimeError,
        ValueError,
        AssertionError,
        asyncmy.errors.Error,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as exc:
        print(
            f"[FAIL] G4 approved recommendation projection apply did not complete: "
            f"{type(exc).__name__}: {exc}"
        )
        return 1
    print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
