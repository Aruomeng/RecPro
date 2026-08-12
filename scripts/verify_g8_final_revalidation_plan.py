#!/usr/bin/env python3
"""Audit readiness for the frozen G8 final revalidation plan.

This command is an append-only filesystem audit.  It validates the plan and
its canonical hash, checks every test/tool reference, inventories historical
artifacts without treating them as final evidence, and optionally validates a
future ``g8-final-runtime-evidence-v1`` envelope.  It never starts a service,
connects to MySQL/Neo4j/Chroma, claims Outbox rows, sends browser business
requests, calls DeepSeek, deletes files, or overwrites an artifact.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Iterable, Mapping

from jsonschema import Draft202012Validator, FormatChecker

from scripts.build_g8_final_revalidation_plan import (
    PLAN_SCHEMA_PATH,
    PROJECT_ROOT,
    canonical_json,
    validate_plan,
)
from scripts.verify_g8_acceptance_coverage import (
    _path_evidence,
    _test_ref_evidence,
    sha256_file,
)


AUDIT_SCHEMA_PATH = PROJECT_ROOT / "contracts" / "verification" / "g8-final-revalidation-audit.schema.json"
RUNTIME_EVIDENCE_SCHEMA_PATH = PROJECT_ROOT / "contracts" / "verification" / "g8-final-runtime-evidence.schema.json"
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")


def validate_run_id(value: str) -> str:
    if RUN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("run id must contain only 3-64 safe characters")
    return value


def resolve_inside_project(value: str | Path, *, label: str) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError(f"{label} must stay inside the repository") from exc
    return resolved


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _validate_instance(schema_path: Path, payload: Mapping[str, Any]) -> list[str]:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(payload),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    return [
        f"{('.'.join(str(part) for part in error.absolute_path) or '<root>')}: {error.message}"
        for error in errors
    ]


def _safe_glob(pattern: str) -> list[Path]:
    raw = Path(pattern)
    if raw.is_absolute() or ".." in raw.parts:
        raise ValueError(f"artifact glob escapes repository: {pattern}")
    return sorted(
        path
        for path in PROJECT_ROOT.glob(pattern)
        if path.is_file() and path.is_relative_to(PROJECT_ROOT)
    )


def _historical_artifacts(patterns: Iterable[str]) -> list[str]:
    paths: dict[str, Path] = {}
    for pattern in patterns:
        for path in _safe_glob(pattern):
            paths[path.relative_to(PROJECT_ROOT).as_posix()] = path
    return sorted(paths)


def _case_reference_report(case: Mapping[str, Any]) -> tuple[bool, bool, list[str]]:
    offline = [_test_ref_evidence(str(ref)) for ref in case["offline_test_refs"]]
    runtime = [_path_evidence(str(ref), label="runtime verifier reference") for ref in case["runtime_verifier_refs"]]
    offline_valid = all(item.get("valid", False) for item in offline)
    runtime_valid = all(item.get("exists", False) for item in runtime)
    blockers: list[str] = []
    if not offline_valid:
        blockers.append("offline_test_reference_invalid")
    if not runtime_valid:
        blockers.append("runtime_verifier_reference_invalid")
    return offline_valid, runtime_valid, blockers


def _load_plan(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, [f"plan unreadable: {type(exc).__name__}: {exc}"]
    if not isinstance(payload, dict):
        return None, ["plan root must be an object"]
    issues = validate_plan(payload)
    return payload, issues


def _load_runtime_evidence(path: Path, plan: Mapping[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, [f"runtime evidence unreadable: {type(exc).__name__}: {exc}"]
    if not isinstance(payload, dict):
        return None, ["runtime evidence root must be an object"]
    issues = _validate_instance(RUNTIME_EVIDENCE_SCHEMA_PATH, payload)
    if payload.get("plan_run_id") != plan.get("run_id"):
        issues.append("runtime evidence plan_run_id does not match the selected plan")
    if payload.get("plan_hash") != plan.get("plan_hash"):
        issues.append("runtime evidence plan_hash does not match the selected plan")
    case_ids = [item.get("case_id") for item in payload.get("cases", []) if isinstance(item, dict)]
    expected = [f"A{index:02d}" for index in range(1, 26)]
    if case_ids != expected:
        issues.append("runtime evidence cases must contain A01-A25 in order")
    safety = payload.get("safety", {})
    for key in (
        "neo4j_writes",
        "chroma_writes",
        "outbox_claims",
        "external_llm_requests",
        "files_deleted",
        "database_physical_deletions",
        "artifact_overwrites",
    ):
        if safety.get(key) != 0:
            issues.append(f"runtime evidence safety.{key} must be 0")
    return payload, issues


def _case_results(
    plan: Mapping[str, Any],
    runtime_evidence: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    evidence_by_case = {
        item["case_id"]: item
        for item in (runtime_evidence or {}).get("cases", [])
        if isinstance(item, dict) and isinstance(item.get("case_id"), str)
    }
    results: list[dict[str, Any]] = []
    for case in plan["cases"]:
        offline_valid, runtime_valid, blockers = _case_reference_report(case)
        historical = _historical_artifacts(case["runtime_artifact_globs"])
        evidence = evidence_by_case.get(case["case_id"])
        final_status = str(evidence.get("status")) if evidence else "PENDING"
        final_paths = [str(item.get("path")) for item in (evidence or {}).get("artifacts", []) if isinstance(item, dict)]
        if not offline_valid or not runtime_valid:
            final_status = "FAIL"
        if evidence is None:
            blockers.append("final_runtime_evidence_not_supplied")
        if case["authorization"] == "SEPARATE_EXACT_CHANGE_PLAN" and evidence is None:
            blockers.append("separate_exact_change_plan_required")
        return_item = {
            "case_id": case["case_id"],
            "execution_mode": case["execution_mode"],
            "authorization": case["authorization"],
            "offline_refs_valid": offline_valid,
            "runtime_refs_valid": runtime_valid,
            "historical_artifact_count": len(historical),
            "final_revalidation": final_status,
            "final_evidence_paths": final_paths,
            "blockers": sorted(set(blockers)),
        }
        results.append(return_item)
    return results


def build_audit(
    *,
    run_id: str,
    plan_path: Path,
    runtime_evidence_path: Path | None = None,
) -> dict[str, Any]:
    run_id = validate_run_id(run_id)
    plan_path = resolve_inside_project(plan_path, label="plan")
    if not plan_path.is_file():
        raise FileNotFoundError(plan_path)
    plan, plan_issues = _load_plan(plan_path)
    if plan is None:
        raise ValueError("; ".join(plan_issues))
    runtime_evidence: dict[str, Any] | None = None
    runtime_issues: list[str] = []
    if runtime_evidence_path is not None:
        evidence_path = resolve_inside_project(runtime_evidence_path, label="runtime evidence")
        if not evidence_path.is_file():
            raise FileNotFoundError(evidence_path)
        runtime_evidence, runtime_issues = _load_runtime_evidence(evidence_path, plan)

    current_commit = _git("rev-parse", "HEAD")
    cases = _case_results(plan, runtime_evidence)
    plan_git_matches = plan["git_commit"] == current_commit
    blockers = list(plan["blockers"])
    if not plan_git_matches:
        blockers.append("selected plan Git commit differs from current checkout")
    if plan_issues:
        blockers.extend(f"plan_validation: {item}" for item in plan_issues)
    if runtime_issues:
        blockers.extend(runtime_issues)
    if runtime_evidence is None:
        blockers.append("final runtime evidence envelope was not supplied")
    for case in cases:
        blockers.extend(f"{case['case_id']}: {item}" for item in case["blockers"])
    browser_scenarios = [
        {
            "scenario_id": item["scenario_id"],
            "fixture_user": item["fixture_user"],
            "state": "BLOCKED_NO_CHANGE_PLAN" if item["write_policy"] == "REQUIRES_SEPARATE_CHANGE_PLAN" else item["state"],
            "write_policy": item["write_policy"],
        }
        for item in plan["browser_scenarios"]
    ]
    final_pass = sum(item["final_revalidation"] == "PASS" for item in cases)
    final_fail = sum(item["final_revalidation"] == "FAIL" for item in cases)
    final_pending = sum(item["final_revalidation"] == "PENDING" for item in cases)
    read_only_ready = sum(
        item["execution_mode"] == "READ_ONLY_RUNTIME" and item["offline_refs_valid"] and item["runtime_refs_valid"]
        for item in cases
    )
    requires_change_plan = sum(item["authorization"] == "SEPARATE_EXACT_CHANGE_PLAN" for item in cases)
    historical_cases = sum(item["historical_artifact_count"] > 0 for item in cases)
    if plan_issues or runtime_issues or final_fail:
        status = "FAIL"
    elif runtime_evidence is not None and final_pass == len(cases) and not final_pending:
        status = "PASS"
    else:
        status = "READY_FOR_RUNTIME"
    return {
        "schema_version": "g8-final-revalidation-audit-v1",
        "status": status,
        "run_id": run_id,
        "audited_at": datetime.now(UTC).isoformat(),
        "git": {
            "current_commit": current_commit,
            "status_before_report": _git("status", "--porcelain"),
        },
        "plan": {
            "path": plan_path.relative_to(PROJECT_ROOT).as_posix(),
            "sha256": sha256_file(plan_path),
            "plan_hash": plan["plan_hash"],
            "plan_git_commit": plan["git_commit"],
            "plan_git_matches_current": plan_git_matches,
            "validation_status": "FAIL" if plan_issues else "PASS",
        },
        "coverage_counts": {
            "total": len(cases),
            "plan_valid": len(cases) if not plan_issues else 0,
            "read_only_ready": read_only_ready,
            "requires_change_plan": requires_change_plan,
            "final_pass": final_pass,
            "final_fail": final_fail,
            "final_pending": final_pending,
            "historical_artifact_cases": historical_cases,
        },
        "cases": cases,
        "browser_scenarios": browser_scenarios,
        "blockers": sorted(set(blockers)),
        "safety": {
            "database_reads": 0,
            "database_writes": 0,
            "neo4j_reads": 0,
            "neo4j_writes": 0,
            "chroma_reads": 0,
            "chroma_writes": 0,
            "outbox_claims": 0,
            "external_llm_requests": 0,
            "files_deleted": 0,
            "database_physical_deletions": 0,
            "artifact_overwrites": 0,
        },
    }


def execute(*, run_id: str, plan_path: Path, runtime_evidence_path: Path | None = None) -> dict[str, Any]:
    run_id = validate_run_id(run_id)
    report = build_audit(run_id=run_id, plan_path=plan_path, runtime_evidence_path=runtime_evidence_path)
    schema_issues = _validate_instance(AUDIT_SCHEMA_PATH, report)
    if schema_issues:
        raise ValueError("generated audit is invalid: " + "; ".join(schema_issues))
    evidence_dir = PROJECT_ROOT / "artifacts" / "verification" / "g8" / run_id
    evidence_dir.mkdir(parents=True, exist_ok=False)
    output_path = evidence_dir / "final-revalidation-audit.json"
    with output_path.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--runtime-evidence", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        execute(run_id=args.run_id, plan_path=args.plan, runtime_evidence_path=args.runtime_evidence)
    except Exception as exc:  # pragma: no cover - CLI boundary
        print(f"[FAIL] final revalidation audit did not complete: {type(exc).__name__}: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
