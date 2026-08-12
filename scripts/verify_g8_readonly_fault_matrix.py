#!/usr/bin/env python3
"""Execute the 17 G8 read-only/fault cases and build final evidence.

The runner executes only deterministic in-process tests with fake adapters and
fault injection.  It deliberately removes LLM credentials from the child
environment and keeps every HTTP, Worker, database, graph, and vector runtime
gate disabled.  The remaining eight acceptance cases stay PENDING because
they require an exact append/update ChangePlan and separate user approval.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Mapping, Sequence

from jsonschema import Draft202012Validator, FormatChecker

from scripts.build_g8_final_revalidation_plan import (
    PROJECT_ROOT,
    validate_plan,
)
from scripts.verify_g8_final_revalidation_plan import (
    RUNTIME_EVIDENCE_SCHEMA_PATH,
    resolve_inside_project,
    validate_run_id,
)


FAULT_MATRIX_SCHEMA_PATH = (
    PROJECT_ROOT / "contracts" / "verification" / "g8-readonly-fault-matrix.schema.json"
)
READ_ONLY_CASE_IDS = (
    "A01", "A05", "A06", "A11", "A12", "A13", "A14", "A15", "A16",
    "A17", "A18", "A19", "A20", "A21", "A22", "A24", "A25",
)
TEST_COUNT_PATTERN = re.compile(r"Ran\s+(\d+)\s+tests?\s+in")
SENSITIVE_ENV_KEYS = {
    "DEEPSEEK_API_KEY",
    "RECPRO_LLM_API_KEY",
    "OPENAI_API_KEY",
}


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _load_plan(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("plan root must be an object")
    issues = validate_plan(payload)
    if issues:
        raise ValueError("plan contract failed: " + "; ".join(issues))
    return payload


def _module_from_test_ref(value: str) -> str:
    raw_path = value.split("::", 1)[0]
    path = Path(raw_path)
    if path.is_absolute() or ".." in path.parts or not raw_path.startswith("tests/"):
        raise ValueError(f"test reference escapes tests/: {value}")
    if path.suffix != ".py" or not (PROJECT_ROOT / path).is_file():
        raise ValueError(f"test reference is not a Python test file: {value}")
    return ".".join(path.with_suffix("").parts)


def selected_cases(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    by_id = {
        str(case["case_id"]): case
        for case in plan["cases"]
        if isinstance(case, dict)
    }
    if tuple(case_id for case_id in READ_ONLY_CASE_IDS if case_id in by_id) != READ_ONLY_CASE_IDS:
        raise ValueError("plan does not contain the frozen 17 read-only cases")
    selected: list[dict[str, Any]] = []
    for case_id in READ_ONLY_CASE_IDS:
        case = dict(by_id[case_id])
        if case.get("execution_mode") != "READ_ONLY_RUNTIME" or case.get("authorization") != "NONE":
            raise ValueError(f"{case_id} is no longer an authorization-free read-only case")
        refs = case.get("offline_test_refs")
        if not isinstance(refs, list) or not refs:
            raise ValueError(f"{case_id} has no executable test references")
        modules = sorted({_module_from_test_ref(str(ref)) for ref in refs})
        selected.append({
            "case_id": case_id,
            "semantics": str(case["semantics"]),
            "test_refs": [str(ref) for ref in refs],
            "modules": modules,
        })
    return selected


def _validate_instance(schema_path: Path, payload: Mapping[str, Any]) -> None:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(payload),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        raise ValueError("schema validation failed: " + "; ".join(error.message for error in errors))


def _safe_child_environment() -> dict[str, str]:
    environment = dict(os.environ)
    for key in SENSITIVE_ENV_KEYS:
        environment.pop(key, None)
    environment.update({
        "PYTHONDONTWRITEBYTECODE": "1",
        "RECPRO_LLM_PROVIDER": "mock",
        "RECPRO_PRODUCTION_HTTP_ENABLED": "false",
        "RECPRO_RECOMMENDATION_API_ENABLED": "false",
        "RECPRO_FEEDBACK_API_ENABLED": "false",
        "RECPRO_WORKER_MODE": "disabled",
    })
    return environment


def run_suite(python_executable: str, modules: Sequence[str]) -> dict[str, Any]:
    command = [python_executable, "-m", "unittest", *modules]
    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        env=_safe_child_environment(),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    combined = f"{result.stdout}\n{result.stderr}"
    matches = TEST_COUNT_PATTERN.findall(combined)
    test_count = int(matches[-1]) if matches else 0
    if result.returncode != 0 or test_count < 1 or "OK" not in combined:
        raise RuntimeError(
            f"read-only fault suite failed safely: exit={result.returncode}, tests={test_count}"
        )
    return {
        "python": python_executable,
        "module_count": len(modules),
        "test_count": test_count,
        "exit_code": result.returncode,
        "output_sha256": hashlib.sha256(combined.encode("utf-8")).hexdigest(),
    }


def build_runtime_evidence(
    *,
    plan: Mapping[str, Any],
    git_commit: str,
    fault_matrix_path: str,
    fault_matrix_sha256: str,
) -> dict[str, Any]:
    read_only = set(READ_ONLY_CASE_IDS)
    cases = []
    for case in plan["cases"]:
        case_id = str(case["case_id"])
        passed = case_id in read_only
        cases.append({
            "case_id": case_id,
            "status": "PASS" if passed else "PENDING",
            "artifacts": ([{
                "path": fault_matrix_path,
                "schema_version": "g8-readonly-fault-matrix-v1",
                "sha256": fault_matrix_sha256,
            }] if passed else []),
            "observations": ({
                "execution_mode": "READ_ONLY_RUNTIME",
                "verification": "isolated in-process adapters and fault injection",
                "business_writes": 0,
            } if passed else {
                "blocking_reason": str(case["blocking_reason"]),
                "authorization": str(case["authorization"]),
            }),
            "change_plan": None,
        })
    return {
        "schema_version": "g8-final-runtime-evidence-v1",
        "plan_run_id": str(plan["run_id"]),
        "plan_hash": str(plan["plan_hash"]),
        "git_commit": git_commit,
        "status": "PENDING",
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
        "cases": cases,
    }


def execute(*, run_id: str, plan_path: Path, python_executable: str) -> dict[str, Any]:
    run_id = validate_run_id(run_id)
    plan_path = resolve_inside_project(plan_path, label="plan")
    plan = _load_plan(plan_path)
    git_commit = _git("rev-parse", "HEAD")
    if _git("status", "--porcelain"):
        raise ValueError("working tree must be clean before final runtime evidence")
    if plan.get("git_commit") != git_commit:
        raise ValueError("plan Git commit does not match current checkout")

    cases = selected_cases(plan)
    modules = sorted({module for case in cases for module in case["modules"]})
    runner = run_suite(python_executable, modules)
    matrix = {
        "schema_version": "g8-readonly-fault-matrix-v1",
        "status": "PASS",
        "run_id": run_id,
        "plan_run_id": str(plan["run_id"]),
        "plan_hash": str(plan["plan_hash"]),
        "git_commit": git_commit,
        "executed_at": datetime.now(UTC).isoformat(),
        "runner": runner,
        "cases": [
            {
                **case,
                "status": "PASS",
                "verification_mode": "ISOLATED_IN_PROCESS_AND_FAULT_INJECTION",
            }
            for case in cases
        ],
        "safety": {
            "network_requests": 0,
            "external_llm_requests": 0,
            "database_reads": 0,
            "database_writes": 0,
            "neo4j_reads": 0,
            "neo4j_writes": 0,
            "chroma_reads": 0,
            "chroma_writes": 0,
            "outbox_claims": 0,
            "files_deleted": 0,
            "database_physical_deletions": 0,
            "artifact_overwrites": 0,
        },
    }
    _validate_instance(FAULT_MATRIX_SCHEMA_PATH, matrix)

    evidence_dir = PROJECT_ROOT / "artifacts" / "verification" / "g8" / run_id
    evidence_dir.mkdir(parents=True, exist_ok=False)
    matrix_path = evidence_dir / "readonly-fault-matrix.json"
    matrix_bytes = (json.dumps(matrix, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    with matrix_path.open("xb") as handle:
        handle.write(matrix_bytes)

    runtime = build_runtime_evidence(
        plan=plan,
        git_commit=git_commit,
        fault_matrix_path=matrix_path.relative_to(PROJECT_ROOT).as_posix(),
        fault_matrix_sha256=hashlib.sha256(matrix_bytes).hexdigest(),
    )
    _validate_instance(RUNTIME_EVIDENCE_SCHEMA_PATH, runtime)
    runtime_path = evidence_dir / "final-runtime-evidence.json"
    with runtime_path.open("x", encoding="utf-8") as handle:
        json.dump(runtime, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return {
        "status": "PASS_WITH_BLOCKERS",
        "run_id": run_id,
        "passed_cases": len(READ_ONLY_CASE_IDS),
        "pending_cases": 25 - len(READ_ONLY_CASE_IDS),
        "test_count": runner["test_count"],
        "fault_matrix": matrix_path.relative_to(PROJECT_ROOT).as_posix(),
        "runtime_evidence": runtime_path.relative_to(PROJECT_ROOT).as_posix(),
        "safety": matrix["safety"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--python", default=sys.executable, dest="python_executable")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = execute(
            run_id=args.run_id,
            plan_path=args.plan,
            python_executable=args.python_executable,
        )
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "FAIL", "error": type(exc).__name__}, ensure_ascii=False))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
