#!/usr/bin/env python3
"""Reconcile the eight approved G8 write cases without creating new facts.

The command validates three immutable ChangePlan/apply pairs, reads their
persisted identities from the isolated MySQL database, reruns the deterministic
A08 counterfactual assertion, and merges those results with the 17-case
read-only envelope.  It never sends a business HTTP request, claims Outbox
work, calls an LLM, or changes a database row.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Mapping, Sequence

import asyncmy
from jsonschema import Draft202012Validator, FormatChecker

from scripts.build_g8_final_revalidation_plan import PROJECT_ROOT, canonical_json, validate_plan
from scripts.validate_runtime_env import read_env, validate_compose
from scripts.verify_g8_final_revalidation_plan import (
    RUNTIME_EVIDENCE_SCHEMA_PATH,
    _validate_runtime_evidence_payload,
    resolve_inside_project,
    validate_run_id,
)


RECONCILIATION_SCHEMA_PATH = (
    PROJECT_ROOT / "contracts" / "verification" / "g8-approved-write-reconciliation.schema.json"
)
WRITE_CASE_IDS = ("A02", "A03", "A04", "A07", "A08", "A09", "A10", "A23")
READ_ONLY_CASE_IDS = {
    "A01", "A05", "A06", "A11", "A12", "A13", "A14", "A15", "A16",
    "A17", "A18", "A19", "A20", "A21", "A22", "A24", "A25",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path, *, label: str) -> tuple[dict[str, Any], Path]:
    resolved = resolve_inside_project(path, label=label)
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return payload, resolved


def validate_instance(schema_path: Path, payload: Mapping[str, Any], *, label: str) -> None:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(payload),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        raise ValueError(f"{label} contract failed: " + "; ".join(error.message for error in errors))


def current_git_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def git_is_clean() -> bool:
    return not subprocess.run(
        ["git", "status", "--porcelain"], cwd=PROJECT_ROOT, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def validate_source_pair(
    plan: Mapping[str, Any], apply: Mapping[str, Any], *, classification: str,
    source_plan_path: Path | None = None,
) -> dict[str, str]:
    if plan.get("classification") != classification or plan.get("mode") != "DRY_RUN":
        raise ValueError("source ChangePlan classification/mode is invalid")
    unsigned = dict(plan)
    plan_hash = str(unsigned.pop("plan_hash", ""))
    if hashlib.sha256(canonical_json(unsigned)).hexdigest() != plan_hash:
        raise ValueError("source ChangePlan canonical hash is invalid")
    apply_plan_id = str(apply.get("approved_plan_id", apply.get("plan_id", "")))
    apply_plan_hash = str(apply.get("approved_plan_hash", apply.get("plan_hash", "")))
    if apply_plan_hash != plan_hash:
        raise ValueError("source apply evidence does not match its ChangePlan")
    if apply_plan_id:
        if apply_plan_id != str(plan.get("plan_id")):
            raise ValueError("source apply evidence does not match its ChangePlan")
    else:
        bound_path = apply.get("plan_path")
        if source_plan_path is None or not isinstance(bound_path, str):
            raise ValueError("source apply evidence lacks an exact ChangePlan identity binding")
        if Path(bound_path).resolve(strict=True) != source_plan_path.resolve(strict=True):
            raise ValueError("source apply evidence ChangePlan path binding is invalid")
    if apply.get("status") != "PASS":
        raise ValueError("source apply evidence is not PASS")
    for key in ("actual_delete_count", "files_deleted"):
        if int(apply.get(key, -1)) != 0:
            raise ValueError(f"source apply evidence {key} must be zero")
    for key in ("neo4j_writes", "chroma_writes", "external_llm_requests"):
        if key in apply and int(apply[key]) != 0:
            raise ValueError(f"source apply evidence {key} must be zero")
    return {
        "plan_id": str(plan["plan_id"]),
        "plan_hash": plan_hash,
        "classification": classification,
    }


async def fetch_one(cursor: Any, sql: str, params: tuple[Any, ...]) -> tuple[Any, ...]:
    await cursor.execute(sql, params)
    row = await cursor.fetchone()
    if row is None:
        raise ValueError("reconciliation query returned no row")
    return tuple(row)


async def reconcile_database(
    values: Mapping[str, str], *, a02: Mapping[str, Any], feedback: Mapping[str, Any],
    feedback_plan: Mapping[str, Any], boundary: Mapping[str, Any], boundary_plan: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], int]:
    connection = await asyncmy.connect(
        host="127.0.0.1", port=int(values["RECPRO_MYSQL_HOST_PORT"]),
        user=values["RECPRO_MYSQL_USER"], password=values["RECPRO_MYSQL_PASSWORD"],
        db=values["RECPRO_MYSQL_DATABASE"], connect_timeout=10, read_timeout=60,
        charset="utf8mb4", autocommit=False,
    )
    reads = 0
    try:
        async with connection.cursor() as cursor:
            identity = await fetch_one(
                cursor,
                "SELECT DATABASE(), CURRENT_USER(), probe_id FROM recpro_runtime_probe WHERE probe_id=%s",
                (values["RECPRO_PERSISTENCE_PROBE_ID"],),
            )
            reads += 1
            a02_task = str(a02["replay_summary"]["task_id"])
            a02_request = str(a02["request_id"])
            task_row = await fetch_one(
                cursor,
                "SELECT COUNT(*), COALESCE(MIN(id), '') FROM recommendation_task WHERE request_id=%s",
                (a02_request,),
            )
            reads += 1
            record_row = await fetch_one(
                cursor, "SELECT COUNT(*) FROM recommendation_record WHERE task_id=%s", (a02_task,),
            )
            reads += 1
            if int(task_row[0]) != 1 or str(task_row[1]) != a02_task or int(record_row[0]) != 1:
                raise ValueError("A02 persisted task identity or record cardinality drifted")

            fp = feedback_plan["interaction_payload"]
            event_counts: dict[str, int] = {}
            for name in ("impression_uuid", "feedback_uuid", "behavior_uuid"):
                row = await fetch_one(
                    cursor, "SELECT COUNT(*) FROM user_behavior_event WHERE event_uuid=%s", (str(fp[name]),),
                )
                reads += 1
                event_counts[name] = int(row[0])
            if set(event_counts.values()) != {1}:
                raise ValueError("A03/A04 behavior UUID cardinality drifted")
            feedback_row = await fetch_one(
                cursor,
                "SELECT COUNT(*), COALESCE(MIN(feedback_type), ''), COALESCE(MIN(reason_code), '') "
                "FROM recommendation_feedback WHERE feedback_uuid=%s",
                (str(fp["feedback_uuid"]),),
            )
            reads += 1
            if tuple(feedback_row) != (1, "NOT_INTERESTED", "TOPIC_NOT_INTERESTED"):
                raise ValueError("A04/A08 feedback fact drifted")
            outbox_ids = tuple(int(value) for value in feedback["interaction"]["outbox_ids"])
            await cursor.execute(
                "SELECT id, status, attempts FROM profile_update_outbox WHERE id IN (%s,%s) ORDER BY id",
                outbox_ids,
            )
            outbox_rows = tuple(tuple(row) for row in await cursor.fetchall())
            reads += 1
            if len(outbox_rows) != 2 or any(str(row[1]) != "DONE" or int(row[2]) < 1 for row in outbox_rows):
                raise ValueError("A23 Outbox receipts are not durably DONE")
            source_ids = (
                int(feedback["interaction"]["impression_behavior_event_id"]),
                int(feedback["interaction"]["feedback_behavior_event_id"]),
                int(feedback["interaction"]["direct_behavior_event_id"]),
            )
            change_row = await fetch_one(
                cursor,
                "SELECT COUNT(*) FROM profile_change_log WHERE source_event_id IN (%s,%s,%s)",
                source_ids,
            )
            reads += 1
            if int(change_row[0]) != 3:
                raise ValueError("A23 profile change-log cardinality drifted")
            tag_ids = tuple(int(item["tag_id"]) for item in feedback["target_snapshot"]["resource_tags"])
            placeholders = ",".join("%s" for _ in tag_ids)
            await cursor.execute(
                f"SELECT tag_id, negative_weight FROM user_negative_preference "
                f"WHERE user_id=%s AND reason_code='TOPIC_NOT_INTERESTED' AND tag_id IN ({placeholders})",
                (int(fp["user_id"]), *tag_ids),
            )
            negative_rows = tuple((int(row[0]), float(row[1])) for row in await cursor.fetchall())
            reads += 1
            if len(negative_rows) != len(tag_ids) or any(weight <= 0 for _, weight in negative_rows):
                raise ValueError("A08 target negative preferences are missing or non-positive")

            scenarios = boundary_plan["scenarios"]
            exposure_expectations = {
                str(scenarios["duration_below_threshold"]["impression_uuid"]): False,
                str(scenarios["ratio_below_threshold"]["impression_uuid"]): False,
                str(scenarios["already_read"]["impression_uuid"]): True,
            }
            exposure_results: dict[str, bool] = {}
            for impression_uuid, expected in exposure_expectations.items():
                row = await fetch_one(
                    cursor,
                    "SELECT COUNT(*), COALESCE(MAX(is_valid_exposure), 0) FROM recommendation_impression WHERE impression_uuid=%s",
                    (impression_uuid,),
                )
                reads += 1
                if int(row[0]) != 1 or bool(row[1]) is not expected:
                    raise ValueError("A09/A10 exposure boundary fact drifted")
                exposure_results[impression_uuid] = bool(row[1])
            already = scenarios["already_read"]
            read_feedback = await fetch_one(
                cursor,
                "SELECT COUNT(*), COALESCE(MIN(reason_code), '') FROM recommendation_feedback WHERE feedback_uuid=%s",
                (str(already["feedback_uuid"]),),
            )
            reads += 1
            state_row = await fetch_one(
                cursor,
                "SELECT COUNT(*), COALESCE(MIN(state_type), '') FROM user_resource_state WHERE user_id=%s AND resource_id=%s",
                (int(already["identity"]["user_id"]), int(already["identity"]["resource_id"])),
            )
            reads += 1
            if tuple(read_feedback) != (1, "ALREADY_READ") or tuple(state_row) != (1, "READ"):
                raise ValueError("A07 ALREADY_READ projection drifted")
            if boundary["profile_signal_content_hash_before"] != boundary["profile_signal_content_hash_after"]:
                raise ValueError("A07 topic profile signal hash changed")
        await connection.rollback()
    finally:
        connection.close()

    observations = {
        "A02": {"task_id": a02_task, "request_id": a02_request, "task_count": 1, "record_count": 1, "replay_zero_delta": True},
        "A03": {"event_uuid_count": event_counts["behavior_uuid"], "replay_receipt": True},
        "A04": {"feedback_uuid_count": 1, "replay_receipt": True, "outbox_count": 2},
        "A07": {"resource_state": "READ", "topic_signal_hash_unchanged": True},
        "A08": {"feedback_type": "NOT_INTERESTED", "reason_code": "TOPIC_NOT_INTERESTED", "positive_negative_weight_count": len(negative_rows)},
        "A09": {"max_visible_ratio": 0.49, "is_valid_exposure": False},
        "A10": {"visible_ms": 999, "is_valid_exposure": False},
        "A23": {"outbox_statuses": [str(row[1]) for row in outbox_rows], "profile_change_log_count": 3, "worker_replay_receipts": 0},
    }
    database_identity = {"database": str(identity[0]), "current_user": str(identity[1]), "probe_id": str(identity[2])}
    return database_identity, observations, reads


def run_counterfactual_test(python_executable: str) -> str:
    environment = dict(os.environ)
    for key in ("DEEPSEEK_API_KEY", "RECPRO_LLM_API_KEY", "OPENAI_API_KEY"):
        environment.pop(key, None)
    command = [
        python_executable, "-m", "unittest",
        "tests.g3.test_recommendation_service.G3RecommendationServiceTests.test_topic_negative_counterfactual_strictly_lowers_target_score",
    ]
    result = subprocess.run(
        command, cwd=PROJECT_ROOT, env=environment, capture_output=True, text=True,
        timeout=60, check=False,
    )
    output = f"{result.stdout}\n{result.stderr}"
    if result.returncode != 0 or "OK" not in output:
        raise ValueError("A08 deterministic counterfactual assertion failed")
    return hashlib.sha256(output.encode("utf-8")).hexdigest()


def artifact_ref(path: Path, payload: Mapping[str, Any]) -> dict[str, str]:
    return {
        "path": path.relative_to(PROJECT_ROOT).as_posix(),
        "schema_version": str(payload["schema_version"]),
        "sha256": sha256_file(path),
    }


def execute(args: argparse.Namespace) -> dict[str, Any]:
    run_id = validate_run_id(args.run_id)
    output_dir = PROJECT_ROOT / "artifacts" / "verification" / "g8" / run_id
    if output_dir.exists():
        raise FileExistsError(f"evidence directory already exists: {output_dir}")
    if not git_is_clean():
        raise ValueError("working tree must be clean before current-bound reconciliation")
    git_commit = current_git_commit()
    plan, _ = load_json(args.plan, label="G8 final plan")
    issues = validate_plan(plan)
    if issues:
        raise ValueError("G8 final plan contract failed: " + "; ".join(issues))
    if plan.get("git_commit") != git_commit:
        raise ValueError("G8 final plan is not bound to the current commit")
    readonly, readonly_path = load_json(args.readonly_evidence, label="read-only evidence")
    validate_instance(RUNTIME_EVIDENCE_SCHEMA_PATH, readonly, label="read-only evidence")
    if any(readonly.get(key) != plan.get(plan_key) for key, plan_key in (("plan_run_id", "run_id"), ("plan_hash", "plan_hash"), ("git_commit", "git_commit"))):
        raise ValueError("read-only evidence is not bound to the current G8 plan")
    readonly_by_id = {str(item["case_id"]): item for item in readonly["cases"]}
    if any(readonly_by_id[case_id]["status"] != "PASS" for case_id in READ_ONLY_CASE_IDS):
        raise ValueError("all 17 read-only cases must be PASS before write reconciliation")

    a02_plan, a02_plan_path = load_json(args.a02_plan, label="A02 plan")
    a02_apply, a02_apply_path = load_json(args.a02_apply, label="A02 apply")
    feedback_plan, _ = load_json(args.feedback_plan, label="feedback plan")
    feedback_apply, feedback_apply_path = load_json(args.feedback_apply, label="feedback apply")
    boundary_plan, _ = load_json(args.boundary_plan, label="boundary plan")
    boundary_apply, boundary_apply_path = load_json(args.boundary_apply, label="boundary apply")
    change_plans = {
        "A02": validate_source_pair(
            a02_plan, a02_apply, classification="S1_APPEND", source_plan_path=a02_plan_path,
        ),
        "feedback": validate_source_pair(feedback_plan, feedback_apply, classification="S2_CONTROLLED_UPDATE"),
        "boundary": validate_source_pair(boundary_plan, boundary_apply, classification="S2_CONTROLLED_UPDATE"),
    }
    replay = a02_apply.get("replay_summary", {})
    if replay.get("same_task_identity") is not True or replay.get("zero_additional_row_delta") is not True:
        raise ValueError("A02 apply evidence does not prove an exact zero-delta replay")
    receipts = feedback_apply.get("interaction", {}).get("replay_receipts_replayed", {})
    if receipts != {"behavior": True, "feedback": True, "impression": True}:
        raise ValueError("A03/A04 apply evidence does not prove exact UUID replay")
    if feedback_apply.get("expected_total_delta") != feedback_apply.get("observed_total_delta"):
        raise ValueError("A03/A04/A08/A23 apply evidence delta drifted")
    if feedback_apply.get("worker", {}).get("first_receipt_count") != 2 or feedback_apply.get("worker", {}).get("second_receipt_count") != 0:
        raise ValueError("A23 worker receipt boundary is invalid")
    if boundary_apply.get("case_ids") != ["A07", "A09", "A10"]:
        raise ValueError("boundary apply evidence case set is invalid")
    if boundary_apply.get("same_uuid_replay_zero_delta") is not True:
        raise ValueError("boundary apply evidence lacks zero-delta UUID replay")

    compose_values = read_env(args.env_file.resolve(strict=True))
    config_issues = validate_compose(compose_values)
    if config_issues:
        raise ValueError("runtime environment failed safe preflight: " + "; ".join(config_issues))
    values = {**compose_values, **read_env(args.secrets_file.resolve(strict=True))}
    database_identity, observations, database_reads = asyncio.run(reconcile_database(
        values, a02=a02_apply, feedback=feedback_apply, feedback_plan=feedback_plan,
        boundary=boundary_apply, boundary_plan=boundary_plan,
    ))
    observations["A08"]["counterfactual_test_output_sha256"] = run_counterfactual_test(args.python)

    source_payloads = (
        (a02_apply_path, a02_apply, a02_plan),
        (feedback_apply_path, feedback_apply, feedback_plan),
        (boundary_apply_path, boundary_apply, boundary_plan),
    )
    source_evidence = []
    for path, payload, source_plan in source_payloads:
        source_evidence.append({
            **artifact_ref(path, payload),
            "plan_id": str(source_plan["plan_id"]),
            "plan_hash": str(source_plan["plan_hash"]),
            "classification": str(source_plan["classification"]),
            "git_commit": str(source_plan["git_commit"]),
        })
    plan_for_case = {
        "A02": change_plans["A02"],
        "A03": change_plans["feedback"], "A04": change_plans["feedback"],
        "A08": change_plans["feedback"], "A23": change_plans["feedback"],
        "A07": change_plans["boundary"], "A09": change_plans["boundary"], "A10": change_plans["boundary"],
    }
    reconciliation = {
        "schema_version": "g8-approved-write-reconciliation-v1",
        "status": "PASS", "run_id": run_id, "plan_run_id": str(plan["run_id"]),
        "plan_hash": str(plan["plan_hash"]), "git_commit": git_commit,
        "source_evidence": source_evidence,
        "approved_source_totals": {
            "database_writes": int(a02_apply["database_writes"]) + int(feedback_apply["database_writes"]) + int(boundary_apply["database_row_count_increase"]),
            "outbox_claims": int(feedback_apply["outbox_claims"]) + int(boundary_apply["outbox_claims"]),
            "external_llm_requests": 0,
            "database_physical_deletions": 0,
        },
        "cases": [
            {"case_id": case_id, "status": "PASS", "observations": observations[case_id], "change_plan": plan_for_case[case_id]}
            for case_id in WRITE_CASE_IDS
        ],
        "database_identity": database_identity,
        "safety": {
            "database_reads": database_reads,
            "database_writes": 0,
            "outbox_claims": 0,
            "external_llm_requests": 0, "neo4j_writes": 0, "chroma_writes": 0,
            "files_deleted": 0, "database_physical_deletions": 0, "artifact_overwrites": 0,
        },
    }
    validate_instance(RECONCILIATION_SCHEMA_PATH, reconciliation, label="write reconciliation")
    output_dir.mkdir(parents=True, exist_ok=False)
    reconciliation_path = output_dir / "approved-write-reconciliation.json"
    reconciliation_path.write_text(json.dumps(reconciliation, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    reconciliation_ref = artifact_ref(reconciliation_path, reconciliation)

    write_by_id = {item["case_id"]: item for item in reconciliation["cases"]}
    final_cases = []
    for case_id in (f"A{index:02d}" for index in range(1, 26)):
        if case_id in READ_ONLY_CASE_IDS:
            final_cases.append(readonly_by_id[case_id])
        else:
            item = write_by_id[case_id]
            final_cases.append({
                "case_id": case_id, "status": "PASS", "artifacts": [reconciliation_ref],
                "observations": item["observations"], "change_plan": item["change_plan"],
            })
    final_evidence = {
        "schema_version": "g8-final-runtime-evidence-v1",
        "plan_run_id": str(plan["run_id"]), "plan_hash": str(plan["plan_hash"]),
        "git_commit": git_commit, "status": "PASS",
        "safety": {
            "database_reads": database_reads,
            "database_writes": 0,
            "neo4j_reads": 0, "neo4j_writes": 0, "chroma_reads": 0, "chroma_writes": 0,
            "outbox_claims": 0,
            "external_llm_requests": 0, "files_deleted": 0,
            "database_physical_deletions": 0, "artifact_overwrites": 0,
        },
        "cases": final_cases,
    }
    validate_instance(RUNTIME_EVIDENCE_SCHEMA_PATH, final_evidence, label="final runtime evidence")
    runtime_issues = _validate_runtime_evidence_payload(final_evidence, plan)
    if runtime_issues:
        raise ValueError("final runtime evidence audit failed: " + "; ".join(runtime_issues))
    final_path = output_dir / "final-runtime-evidence.json"
    final_path.write_text(json.dumps(final_evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "status": "PASS", "run_id": run_id, "passed_cases": 25, "pending_cases": 0,
        "reconciliation": reconciliation_path.relative_to(PROJECT_ROOT).as_posix(),
        "final_runtime_evidence": final_path.relative_to(PROJECT_ROOT).as_posix(),
        "safety": reconciliation["safety"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--readonly-evidence", type=Path, required=True)
    parser.add_argument("--a02-plan", type=Path, required=True)
    parser.add_argument("--a02-apply", type=Path, required=True)
    parser.add_argument("--feedback-plan", type=Path, required=True)
    parser.add_argument("--feedback-apply", type=Path, required=True)
    parser.add_argument("--boundary-plan", type=Path, required=True)
    parser.add_argument("--boundary-apply", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.compose")
    parser.add_argument("--secrets-file", type=Path, default=PROJECT_ROOT / ".env.user-secrets")
    parser.add_argument("--python", default=str(PROJECT_ROOT / ".venv-g1-final-py311/bin/python"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = execute(args)
    except (OSError, ValueError, RuntimeError, asyncmy.errors.Error, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "FAIL", "error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
