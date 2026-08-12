#!/usr/bin/env python3
"""Build an append-only, read-only plan for final A01-A25 revalidation.

The plan freezes the acceptance matrix, the repository commit, the existing
offline evidence references, and the six browser fixture boundaries.  It does
not start a service, connect to a database, claim an Outbox row, send a
browser business request, call DeepSeek, or alter an existing artifact.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker

from scripts.verify_g8_acceptance_coverage import (
    CASE_COVERAGE,
    PROJECT_ROOT,
    parse_acceptance_matrix,
    sha256_file,
)


PLAN_SCHEMA_PATH = PROJECT_ROOT / "contracts" / "verification" / "g8-final-revalidation-plan.schema.json"
MATRIX_PATH = PROJECT_ROOT / "docs" / "acceptance_matrix.md"
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")


def validate_run_id(value: str) -> str:
    if RUN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("run id must contain only 3-64 safe characters")
    return value


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _case_plan(row: Mapping[str, str]) -> dict[str, Any]:
    mapping = CASE_COVERAGE[row["case_id"]]
    return {
        "case_id": row["case_id"],
        "first_gate": row["first_gate"],
        "final_gate": row["final_gate"],
        "semantics": row["semantics"],
        "evidence_type": row["evidence_type"],
        "offline_test_refs": list(mapping["test_refs"]),
        "runtime_verifier_refs": list(mapping["tool_refs"]),
        "runtime_artifact_globs": list(mapping["artifact_globs"]),
        "required_evidence": [
            "runtime_result_status",
            "artifact_sha256_and_schema",
            "environment_and_config_fingerprint",
            "safety_counters_and_before_after_counts",
        ],
    }


def _browser_scenarios() -> list[dict[str, Any]]:
    evidence = [
        "browser_trace_and_dom_assertions",
        "screenshot_or_accessibility_snapshot",
        "request_response_and_idempotency_log",
        "database_count_reconciliation",
    ]
    return [
        {
            "scenario_id": "cold_user_guided",
            "fixture_user": "demo_cold",
            "state": "PENDING",
            "write_policy": "REQUIRES_SEPARATE_CHANGE_PLAN",
            "required_evidence": evidence,
        },
        {
            "scenario_id": "clear_user_recommendation",
            "fixture_user": "demo_clear",
            "state": "PENDING",
            "write_policy": "REQUIRES_SEPARATE_CHANGE_PLAN",
            "required_evidence": evidence,
        },
        {
            "scenario_id": "topic_user_explanation",
            "fixture_user": "demo_topic",
            "state": "PENDING",
            "write_policy": "REQUIRES_SEPARATE_CHANGE_PLAN",
            "required_evidence": evidence,
        },
        {
            "scenario_id": "reading_path_clarification",
            "fixture_user": "demo_path",
            "state": "PENDING",
            "write_policy": "REQUIRES_SEPARATE_CHANGE_PLAN",
            "required_evidence": evidence,
        },
        {
            "scenario_id": "negative_feedback_adjustment",
            "fixture_user": "demo_negative",
            "state": "PENDING",
            "write_policy": "REQUIRES_SEPARATE_CHANGE_PLAN",
            "required_evidence": evidence,
        },
        {
            "scenario_id": "degraded_dependency_path",
            "fixture_user": "demo_degraded",
            "state": "PENDING",
            "write_policy": "REQUIRES_SEPARATE_CHANGE_PLAN",
            "required_evidence": evidence,
        },
    ]


def build_plan(*, run_id: str, matrix_path: Path = MATRIX_PATH, git_commit: str | None = None) -> dict[str, Any]:
    run_id = validate_run_id(run_id)
    if not matrix_path.is_file():
        raise FileNotFoundError(matrix_path)
    rows = parse_acceptance_matrix(matrix_path)
    case_ids = [row["case_id"] for row in rows]
    expected_case_ids = [f"A{index:02d}" for index in range(1, 26)]
    if case_ids != expected_case_ids:
        raise ValueError("acceptance matrix must contain A01-A25 in order")
    commit = git_commit or _git("rev-parse", "HEAD")
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise ValueError("git commit must be a 40-character hexadecimal SHA")
    plan: dict[str, Any] = {
        "schema_version": "g8-final-revalidation-plan-v1",
        "status": "PLAN_READY_WITH_BLOCKERS",
        "run_id": run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "git_commit": commit,
        "matrix": {
            "path": matrix_path.relative_to(PROJECT_ROOT).as_posix(),
            "sha256": sha256_file(matrix_path),
            "case_ids": case_ids,
        },
        "mode": "READ_ONLY",
        "cases": [_case_plan(row) for row in rows],
        "browser_scenarios": _browser_scenarios(),
        "safety_assertions": {
            "database_writes": 0,
            "neo4j_writes": 0,
            "chroma_writes": 0,
            "outbox_claims": 0,
            "external_llm_requests": 0,
            "file_deletions": 0,
            "database_physical_deletions": 0,
            "artifact_overwrites": 0,
            "business_post_authorization": False,
        },
        "blockers": [
            "A01-A25 final runtime evidence has not yet been executed.",
            "All six browser business scenarios require a separate exact ChangePlan and user approval.",
            "Production OIDC/JWKS, DeepSeek external-call review, and G9 formal input freeze remain pending.",
        ],
    }
    plan["plan_hash"] = sha256_bytes(canonical_json(plan))
    return plan


def validate_plan(plan: Mapping[str, Any]) -> list[str]:
    errors = sorted(
        Draft202012Validator(
            json.loads(PLAN_SCHEMA_PATH.read_text(encoding="utf-8")),
            format_checker=FormatChecker(),
        ).iter_errors(plan),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    issues = [
        f"{('.'.join(str(part) for part in error.absolute_path) or '<root>')}: {error.message}"
        for error in errors
    ]
    unsigned = dict(plan)
    expected_hash = unsigned.pop("plan_hash", None)
    if not isinstance(expected_hash, str) or expected_hash != sha256_bytes(canonical_json(unsigned)):
        issues.append("plan_hash: does not match canonical plan contents")
    return issues


def execute(*, run_id: str, matrix_path: Path = MATRIX_PATH) -> dict[str, Any]:
    run_id = validate_run_id(run_id)
    evidence_dir = PROJECT_ROOT / "artifacts" / "verification" / "g8" / run_id
    evidence_dir.mkdir(parents=True, exist_ok=False)
    plan = build_plan(run_id=run_id, matrix_path=matrix_path)
    issues = validate_plan(plan)
    if issues:
        raise ValueError("generated final revalidation plan is invalid: " + "; ".join(issues))
    output_path = evidence_dir / "final-revalidation-plan.json"
    with output_path.open("x", encoding="utf-8") as handle:
        json.dump(plan, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
    return plan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--matrix", type=Path, default=MATRIX_PATH)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        execute(run_id=args.run_id, matrix_path=args.matrix)
    except Exception as exc:  # pragma: no cover - CLI boundary
        print(f"[FAIL] final revalidation plan did not complete: {type(exc).__name__}: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
