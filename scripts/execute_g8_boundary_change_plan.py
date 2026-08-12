#!/usr/bin/env python3
"""Apply one explicitly approved G8 A07/A09/A10 boundary ChangePlan.

The executor is fail-closed and bounded to three impressions, one ALREADY_READ
feedback, and the single Outbox row created by that feedback. It has no delete,
migration, graph/vector, HTTP, or external-LLM capability.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping, Sequence
from uuid import UUID

import asyncmy
from jsonschema import Draft202012Validator, FormatChecker

from backend.app.composition import build_profile_outbox_worker, build_research_feedback_service
from backend.app.feedback.domain.public import FeedbackCommand, ImpressionCommand
from backend.app.shared_kernel.contracts.enums import FeedbackType, NegativeReasonCode
from scripts.build_g5_feedback_http_plan import (
    canonical,
    connect_runtime,
    load_pass_baseline,
    read_identity_and_grants,
    read_snapshot,
    read_target_facts,
    sha256_bytes,
    target_snapshot_from_facts,
)
from scripts.build_g8_boundary_change_plan import (
    EXPECTED_DELTAS,
    OPERATIONS,
    SCHEMA_PATH,
    _parse_time,
)
from scripts.validate_runtime_env import read_env, validate_compose
from scripts.verify_g7_mysql_http_readonly import build_settings


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_SCHEMA_PATH = (
    PROJECT_ROOT / "contracts" / "verification" / "g8-boundary-apply-evidence.schema.json"
)
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
INTERACTION_DELTAS = {
    "recommendation_impression": 3,
    "recommendation_feedback": 1,
    "user_behavior_event": 4,
    "profile_update_outbox": 1,
    "user_resource_state": 1,
    "profile_replay_run": 0,
    "profile_change_log": 0,
    "user_interest_tag": 0,
    "user_negative_preference": 0,
    "domain_state_transition": 2,
    "user_profile": 0,
}


def resolve_inside_root(value: Path, *, label: str) -> Path:
    candidate = value if value.is_absolute() else PROJECT_ROOT / value
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError(f"{label} must resolve inside the repository") from exc
    return resolved


def current_git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, check=True, capture_output=True, text=True
    )
    commit = result.stdout.strip()
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise ValueError("current Git HEAD is not a full commit")
    return commit


def require_clean_worktree() -> None:
    result = subprocess.run(
        ["git", "status", "--porcelain"], cwd=PROJECT_ROOT, check=True, capture_output=True, text=True
    )
    if result.stdout.strip():
        raise ValueError("working tree must be clean when applying an approved plan")


def load_and_validate_plan(
    path: Path, *, approved_plan_id: str, approved_plan_hash: str
) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("G8 boundary ChangePlan must contain a JSON object")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(payload))
    if errors:
        raise ValueError("G8 boundary ChangePlan violates its schema")
    if payload["plan_id"] != approved_plan_id:
        raise ValueError("approved plan id does not match the ChangePlan")
    if HASH_PATTERN.fullmatch(approved_plan_hash) is None or payload["plan_hash"] != approved_plan_hash:
        raise ValueError("approved plan hash does not match the ChangePlan")
    unsigned = dict(payload)
    unsigned.pop("plan_hash")
    if sha256_bytes(canonical(unsigned)) != approved_plan_hash:
        raise ValueError("ChangePlan canonical hash does not match plan_hash")
    if payload["classification"] != "S2_CONTROLLED_UPDATE" or payload["mode"] != "DRY_RUN":
        raise ValueError("only an S2_CONTROLLED_UPDATE DRY_RUN plan may be applied")
    if payload["case_ids"] != ["A07", "A09", "A10"]:
        raise ValueError("ChangePlan case set is not the bounded G8 boundary set")
    if payload["executor_status"] != "READY_FOR_EXPLICIT_APPROVAL":
        raise ValueError("ChangePlan is not executable")
    if payload["safety_assertions"] != {
        "file_deletions": 0,
        "database_physical_deletions": 0,
        "artifact_overwrites": 0,
        "destructive_capabilities_required": False,
        "counts_must_not_decrease": True,
        "business_writes_authorized": False,
    }:
        raise ValueError("ChangePlan safety assertions are not zero-destructive")
    observed = {str(item["table"]): int(item["expected_delta"]) for item in payload["targets"]}
    if observed != EXPECTED_DELTAS or payload["max_changes"] != sum(EXPECTED_DELTAS.values()):
        raise ValueError("ChangePlan target deltas differ from the bounded executor contract")
    for target in payload["targets"]:
        table = str(target["table"])
        before = int(target["expected_before_count"])
        delta = int(target["expected_delta"])
        if target["operation"] != OPERATIONS[table]:
            raise ValueError(f"ChangePlan operation differs from the executor contract for {table}")
        if int(target["expected_after_count"]) != before + delta:
            raise ValueError(f"ChangePlan after-count arithmetic is invalid for {table}")
    scenarios = payload["scenarios"]
    duration = scenarios["duration_below_threshold"]
    ratio = scenarios["ratio_below_threshold"]
    already_read = scenarios["already_read"]
    if (duration["visible_ms"], float(duration["max_visible_ratio"])) != (999, 0.8):
        raise ValueError("A09 must freeze the exact 999ms/0.8 duration boundary")
    if (ratio["visible_ms"], float(ratio["max_visible_ratio"])) != (1000, 0.49):
        raise ValueError("A10 must freeze the exact 1000ms/0.49 ratio boundary")
    if (already_read["visible_ms"], float(already_read["max_visible_ratio"])) != (1500, 0.8):
        raise ValueError("A07 must use the frozen valid-exposure control")
    uuid_values = (
        duration["impression_uuid"],
        ratio["impression_uuid"],
        already_read["impression_uuid"],
        already_read["feedback_uuid"],
    )
    if len(set(uuid_values)) != 4:
        raise ValueError("all four boundary interaction UUIDs must be distinct")
    if duration["identity"] != ratio["identity"]:
        raise ValueError("A09 and A10 must use the same frozen exposure target")
    if duration["identity"]["resource_id"] == already_read["identity"]["resource_id"]:
        raise ValueError("A07 and exposure boundaries must use distinct resources")
    shared_identity_keys = ("task_id", "record_id", "user_id")
    if any(duration["identity"][key] != already_read["identity"][key] for key in shared_identity_keys):
        raise ValueError("all boundary scenarios must share one task, record, and user")
    timestamps = (
        _parse_time(str(duration["rendered_at"])),
        _parse_time(str(ratio["rendered_at"])),
        _parse_time(str(already_read["rendered_at"])),
        _parse_time(str(already_read["feedback_at"])),
    )
    if tuple(sorted(timestamps)) != timestamps or len(set(timestamps)) != 4:
        raise ValueError("boundary scenario timestamps must be strictly increasing")
    return payload


async def snapshot(values: Mapping[str, str]) -> tuple[tuple[str, ...], dict[str, int]]:
    connection = await connect_runtime(values)
    try:
        return await read_snapshot(connection)
    finally:
        connection.close()


def assert_delta(
    before: Mapping[str, int], after: Mapping[str, int], expected: Mapping[str, int]
) -> None:
    for table, delta in expected.items():
        observed = int(after[table]) - int(before[table])
        if observed != delta:
            raise ValueError(f"count delta mismatch for {table}: expected {delta}, observed {observed}")


async def profile_content_snapshot(values: Mapping[str, str], *, user_id: int) -> dict[str, Any]:
    connection = await connect_runtime(values)
    try:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT tag_id, positive_weight, raw_positive_signal, source_count, last_event_at "
                "FROM user_interest_tag WHERE user_id=%s ORDER BY tag_id",
                (user_id,),
            )
            interests = await cursor.fetchall()
            await cursor.execute(
                "SELECT tag_id, reason_code, negative_weight, raw_negative_signal, source_count, "
                "expires_at, last_event_at FROM user_negative_preference WHERE user_id=%s "
                "ORDER BY tag_id, reason_code",
                (user_id,),
            )
            negatives = await cursor.fetchall()
    finally:
        connection.close()

    def normalized(rows: Sequence[Sequence[Any]]) -> list[list[str | None]]:
        return [[None if value is None else str(value) for value in row] for row in rows]

    content = {
        "interests": normalized(interests),
        "negatives": normalized(negatives),
    }
    return {"sha256": sha256_bytes(canonical(content)), "content": content}


async def read_outbox_statuses(values: Mapping[str, str]) -> dict[str, int]:
    connection = await connect_runtime(values)
    try:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT status, COUNT(*) FROM profile_update_outbox GROUP BY status ORDER BY status"
            )
            return {str(row[0]): int(row[1]) for row in await cursor.fetchall()}
    finally:
        connection.close()


async def target_facts(
    values: Mapping[str, str], *, scenario: Mapping[str, Any], feedback_uuid: UUID, behavior_uuid: UUID
) -> dict[str, Any]:
    identity = scenario["identity"]
    connection = await connect_runtime(values)
    try:
        return await read_target_facts(
            connection,
            task_id=str(identity["task_id"]),
            record_id=int(identity["record_id"]),
            item_id=int(identity["item_id"]),
            user_id=int(identity["user_id"]),
            resource_id=int(identity["resource_id"]),
            uuids={
                "impression_uuid": UUID(str(scenario["impression_uuid"])),
                "feedback_uuid": feedback_uuid,
                "behavior_uuid": behavior_uuid,
            },
        )
    finally:
        connection.close()


def impression_command(scenario: Mapping[str, Any], facts: Mapping[str, Any]) -> ImpressionCommand:
    return ImpressionCommand(
        impression_uuid=UUID(str(scenario["impression_uuid"])),
        recommendation_item_id=int(scenario["identity"]["item_id"]),
        user_id=int(scenario["identity"]["user_id"]),
        position=int(facts["item"]["rank_no"]),
        rendered_at=_parse_time(str(scenario["rendered_at"])),
        visible_started_at=_parse_time(str(scenario["rendered_at"])),
        visible_ms=int(scenario["visible_ms"]),
        max_visible_ratio=float(scenario["max_visible_ratio"]),
    )


async def execute(args: argparse.Namespace) -> dict[str, Any]:
    if RUN_ID_PATTERN.fullmatch(args.run_id) is None:
        raise ValueError("run id must use 3-64 safe characters")
    evidence_dir = PROJECT_ROOT / "artifacts" / "verification" / "g8" / args.run_id
    if evidence_dir.exists():
        raise FileExistsError(f"evidence directory already exists: {evidence_dir}")
    plan_path = resolve_inside_root(args.plan, label="G8 boundary ChangePlan")
    baseline_path = resolve_inside_root(args.baseline, label="G5 read-only baseline")
    plan = load_and_validate_plan(
        plan_path, approved_plan_id=args.plan_id, approved_plan_hash=args.approved_plan_hash
    )
    if current_git_commit() != plan["git_commit"]:
        raise ValueError("runtime code changed after plan review; regenerate the plan")
    require_clean_worktree()
    compose = read_env(resolve_inside_root(args.env_file, label="runtime env file"))
    values = {**compose, **read_env(resolve_inside_root(args.secrets_file, label="secrets file"))}
    issues = validate_compose(compose)
    if issues:
        raise ValueError("runtime environment failed safe preflight: " + "; ".join(issues))
    required = (
        "COMPOSE_PROJECT_NAME", "RECPRO_MYSQL_HOST_PORT", "RECPRO_MYSQL_DATABASE",
        "RECPRO_MYSQL_USER", "RECPRO_MYSQL_PASSWORD", "RECPRO_MYSQL_MIGRATION_USER",
        "RECPRO_MYSQL_MIGRATION_PASSWORD", "RECPRO_PERSISTENCE_PROBE_ID",
    )
    missing = [key for key in required if not values.get(key)]
    if missing:
        raise ValueError(f"missing required runtime keys: {missing}")
    baseline, baseline_raw = load_pass_baseline(baseline_path)
    if plan["baseline"]["path"] != baseline_path.relative_to(PROJECT_ROOT).as_posix():
        raise ValueError("approved baseline path differs from the supplied baseline")
    if hashlib.sha256(baseline_raw).hexdigest() != plan["baseline"]["sha256"]:
        raise ValueError("approved baseline hash changed")
    if baseline["compose_project"] != values["COMPOSE_PROJECT_NAME"]:
        raise ValueError("baseline Compose project does not match runtime")
    expected_environment = {
        "environment_id": values["COMPOSE_PROJECT_NAME"],
        "workspace": str(PROJECT_ROOT),
        "database_identity": f"mysql://{values['COMPOSE_PROJECT_NAME']}/{values['RECPRO_MYSQL_DATABASE']}",
        "host_fingerprint": "sha256:" + sha256_bytes(
            f"{values['COMPOSE_PROJECT_NAME']}:{values['RECPRO_MYSQL_DATABASE']}:{PROJECT_ROOT}:{plan['git_commit']}".encode(
                "utf-8"
            )
        ),
    }
    if plan["environment"] != expected_environment:
        raise ValueError("approved environment identity differs from runtime")
    before_names, before_counts = await snapshot(values)
    baseline_counts = {str(key): int(value) for key, value in baseline["after_counts"].items()}
    if before_names != tuple(sorted(baseline_counts)) or before_counts != baseline_counts:
        raise ValueError("live full counts differ from the approved baseline")
    if sha256_bytes(canonical(dict(sorted(before_counts.items())))) != plan["baseline"]["counts_sha256"]:
        raise ValueError("approved baseline count hash differs from live counts")
    for target in plan["targets"]:
        table = str(target["table"])
        if before_counts[table] != int(target["expected_before_count"]):
            raise ValueError(f"target count differs from plan for {table}")
    identity = await read_identity_and_grants(values)
    if not identity.get("grants_safe"):
        raise ValueError("runtime grants failed the least-privilege guard")
    statuses_before = await read_outbox_statuses(values)
    if statuses_before.get("PENDING", 0) or statuses_before.get("PROCESSING", 0):
        raise ValueError(f"pre-existing live Outbox work is not allowed: {statuses_before}")

    scenarios = plan["scenarios"]
    duration = scenarios["duration_below_threshold"]
    ratio = scenarios["ratio_below_threshold"]
    already_read = scenarios["already_read"]
    exposure_facts = await target_facts(
        values,
        scenario=duration,
        feedback_uuid=UUID(str(already_read["feedback_uuid"])),
        behavior_uuid=UUID(str(ratio["impression_uuid"])),
    )
    read_facts = await target_facts(
        values,
        scenario=already_read,
        feedback_uuid=UUID(str(already_read["feedback_uuid"])),
        behavior_uuid=UUID(str(ratio["impression_uuid"])),
    )
    for scenario, facts in ((duration, exposure_facts), (ratio, exposure_facts), (already_read, read_facts)):
        observed_hash = sha256_bytes(canonical(target_snapshot_from_facts(facts)))
        if observed_hash != scenario["identity"]["target_snapshot_sha256"]:
            raise ValueError("live target snapshot differs from the approved plan")
    user_id = int(already_read["identity"]["user_id"])
    profile_before = await profile_content_snapshot(values, user_id=user_id)

    settings = build_settings(dict(values))
    feedback_service = build_research_feedback_service(settings)
    commands = (
        impression_command(duration, exposure_facts),
        impression_command(ratio, exposure_facts),
        impression_command(already_read, read_facts),
    )
    impression_receipts = tuple([await feedback_service.record_impression(command) for command in commands])
    if tuple(receipt.is_valid_exposure for receipt in impression_receipts) != (False, False, True):
        raise ValueError("observed exposure-boundary results differ from the approved semantics")
    feedback_command = FeedbackCommand(
        feedback_uuid=UUID(str(already_read["feedback_uuid"])),
        recommendation_item_id=int(already_read["identity"]["item_id"]),
        user_id=user_id,
        feedback_type=FeedbackType.NOT_INTERESTED,
        occurred_at=_parse_time(str(already_read["feedback_at"])),
        impression_uuid=UUID(str(already_read["impression_uuid"])),
        reason_code=NegativeReasonCode.ALREADY_READ,
    )
    feedback_receipt = await feedback_service.record_feedback(feedback_command)
    if feedback_receipt.outbox_id is None or feedback_receipt.resource_state is None:
        raise ValueError("ALREADY_READ must create one Outbox row and one resource state")
    if feedback_receipt.resource_state.get("state_type") != "READ":
        raise ValueError("ALREADY_READ created a resource state other than READ")
    interaction_names, interaction_counts = await snapshot(values)
    if interaction_names != before_names:
        raise ValueError("boundary interaction changed the database table set")
    assert_delta(before_counts, interaction_counts, INTERACTION_DELTAS)
    for table in before_counts:
        if table not in INTERACTION_DELTAS and interaction_counts[table] != before_counts[table]:
            raise ValueError(f"boundary interaction changed a non-target table: {table}")

    replay_impressions = tuple([await feedback_service.record_impression(command) for command in commands])
    replay_feedback = await feedback_service.record_feedback(feedback_command)
    replay_names, replay_counts = await snapshot(values)
    if replay_names != interaction_names or replay_counts != interaction_counts:
        raise ValueError("same-UUID boundary replay changed database counts")
    if not all(receipt.replayed for receipt in replay_impressions) or not replay_feedback.replayed:
        raise ValueError("same-UUID boundary replay was not reported as replayed")

    async def worker_connection_factory() -> Any:
        return await asyncmy.connect(
            host="127.0.0.1",
            port=int(values["RECPRO_MYSQL_HOST_PORT"]),
            user=values["RECPRO_MYSQL_MIGRATION_USER"],
            password=values["RECPRO_MYSQL_MIGRATION_PASSWORD"],
            db=values["RECPRO_MYSQL_DATABASE"],
            connect_timeout=10,
            read_timeout=60,
            charset="utf8mb4",
            autocommit=False,
        )

    worker = build_profile_outbox_worker(
        settings,
        connection_factory=worker_connection_factory,
        worker_id=str(already_read["worker_id"]),
        formula_version=str(already_read["formula_version"]),
    )
    receipts = await worker.run_once(limit=1)
    second_receipts = await worker.run_once(limit=1)
    if len(receipts) != 1 or second_receipts:
        raise ValueError("Worker must consume exactly one new row and none on replay")
    if int(receipts[0].source_event_id) != int(feedback_receipt.behavior_event_id):
        raise ValueError("Worker consumed an unexpected source event")
    after_names, after_counts = await snapshot(values)
    if after_names != before_names:
        raise ValueError("boundary apply changed the database table set")
    assert_delta(before_counts, after_counts, EXPECTED_DELTAS)
    for table in before_counts:
        if table not in EXPECTED_DELTAS and after_counts[table] != before_counts[table]:
            raise ValueError(f"boundary apply changed a protected/non-target table: {table}")
    statuses_after = await read_outbox_statuses(values)
    if statuses_after.get("PENDING", 0) or statuses_after.get("PROCESSING", 0):
        raise ValueError(f"Worker left live Outbox work: {statuses_after}")
    profile_after = await profile_content_snapshot(values, user_id=user_id)
    if profile_after["sha256"] != profile_before["sha256"]:
        raise ValueError("ALREADY_READ changed interest-tag or negative-preference content")

    evidence = {
        "schema_version": "g8-boundary-apply-evidence-v1",
        "status": "PASS",
        "run_id": args.run_id,
        "plan_id": plan["plan_id"],
        "plan_hash": plan["plan_hash"],
        "git_commit": plan["git_commit"],
        "case_ids": plan["case_ids"],
        "before_counts": before_counts,
        "after_interaction_counts": interaction_counts,
        "after_counts": after_counts,
        "observed_deltas": {table: after_counts[table] - before_counts[table] for table in EXPECTED_DELTAS},
        "exposure_validity": {
            "duration_999ms": bool(impression_receipts[0].is_valid_exposure),
            "ratio_0_49": bool(impression_receipts[1].is_valid_exposure),
            "valid_control": bool(impression_receipts[2].is_valid_exposure),
        },
        "already_read_state": feedback_receipt.resource_state,
        "same_uuid_replay_zero_delta": True,
        "worker": {"first_receipt_count": 1, "second_receipt_count": 0, "statuses_after": statuses_after},
        "profile_signal_content_hash_before": profile_before["sha256"],
        "profile_signal_content_hash_after": profile_after["sha256"],
        "database_row_count_increase": sum(EXPECTED_DELTAS.values()),
        "controlled_projection_updates": [
            "profile_update_outbox",
            "user_profile",
            "user_interest_tag",
            "user_negative_preference",
        ],
        "outbox_claims": 1,
        "business_posts": 0,
        "external_llm_requests": 0,
        "neo4j_writes": 0,
        "chroma_writes": 0,
        "actual_delete_count": 0,
        "files_deleted": 0,
        "overwritten_inputs": 0,
        "identity": identity,
    }
    evidence_schema = json.loads(EVIDENCE_SCHEMA_PATH.read_text(encoding="utf-8"))
    evidence_errors = list(
        Draft202012Validator(evidence_schema, format_checker=FormatChecker()).iter_errors(evidence)
    )
    if evidence_errors:
        raise ValueError("G8 boundary apply evidence violates its schema")
    evidence_dir.mkdir(parents=True, exist_ok=False)
    evidence_path = evidence_dir / "g8-boundary-apply.json"
    with evidence_path.open("x", encoding="utf-8") as handle:
        json.dump(evidence, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return evidence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-id", required=True)
    parser.add_argument("--approved-plan-hash", required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.compose")
    parser.add_argument("--secrets-file", type=Path, default=PROJECT_ROOT / ".env.user-secrets")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        evidence = asyncio.run(execute(args))
    except (
        OSError,
        RuntimeError,
        ValueError,
        subprocess.SubprocessError,
        asyncmy.errors.Error,
        json.JSONDecodeError,
    ) as exc:
        print(json.dumps({"status": "FAIL", "error": type(exc).__name__}, ensure_ascii=False))
        return 1
    print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
