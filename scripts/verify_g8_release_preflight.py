#!/usr/bin/env python3
"""Build an append-only, no-database G8 release-candidate preflight report.

This command is intentionally a release *preflight*, not a claim that G8 is
complete.  It runs the repository's static gates, selected backend/frontend
tests, a fresh immutable frontend build, and a local backend-image inspection.
It also verifies that the default Compose/API/Worker/LLM settings remain
fail-closed.  No application process is started and no database, graph,
vector-store, or external-provider request is made.

The report directory must not already exist.  Existing evidence is therefore
never overwritten, and this command has no cleanup or destructive mode.
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
import time
from typing import Any, Mapping, Sequence

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")

REQUIRED_FILES = (
    "compose.yaml",
    ".env.compose.example",
    ".env.host.example",
    "backend/Dockerfile",
    "backend/app/main.py",
    "backend/app/config.py",
    "backend/app/g4_feedback_demo_main.py",
    "backend/app/worker.py",
    "frontend/package-lock.json",
    "frontend/src/App.vue",
    "frontend/src/api/interactionClient.ts",
    "contracts/config/examples/rec-1.0.0.json",
    "contracts/prompts/rec-prompts-v1.0.0.json",
)

EXPECTED_BACKEND_COMMAND = (
    "python",
    "-m",
    "uvicorn",
    "backend.app.main:app",
    "--host",
    "0.0.0.0",
    "--port",
    "8000",
)
EXPECTED_WORKER_COMMAND = ("python", "-m", "backend.app.worker")

DEFAULT_BLOCKERS = (
    {
        "code": "A01_A25_FINAL_REVALIDATION_PENDING",
        "message": "A01-A25 final G8 revalidation is not yet complete.",
    },
    {
        "code": "BROWSER_E2E_SIX_SCENARIOS_PENDING",
        "message": "The six-scenario browser E2E suite is not yet frozen and passed.",
    },
    {
        "code": "G5_REAL_BROWSER_WRITE_REQUIRES_CHANGE_PLAN",
        "message": "A real G5 browser write requires a new exact ChangePlan and approval.",
    },
    {
        "code": "G5_NON_EMPTY_WORKER_REQUIRES_CHANGE_PLAN",
        "message": "A non-empty Profile Outbox run requires a separate exact ChangePlan and approval.",
    },
    {
        "code": "PRODUCTION_OIDC_JWKS_PENDING",
        "message": "Production OIDC/JWKS and deployment credentials are not frozen.",
    },
    {
        "code": "DEEPSEEK_EXTERNAL_CALL_REVIEW_PENDING",
        "message": "DeepSeek external-call, cost, privacy, and prompt review is still pending.",
    },
    {
        "code": "G9_EVALUATION_INPUTS_BLOCKED",
        "message": "G9 evaluation inputs remain PASS_WITH_BLOCKERS; no confirmation experiment may start.",
    },
)


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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not key.strip():
            raise ValueError(f"invalid environment assignment at {path}:{line_number}")
        normalized = key.strip()
        if normalized in values:
            raise ValueError(f"duplicate environment key at {path}:{line_number}: {normalized}")
        values[normalized] = value.strip().strip('"').strip("'")
    return values


def _default_false(value: object) -> bool:
    return isinstance(value, str) and value.endswith(":-false}")


def inspect_fail_closed_defaults() -> dict[str, Any]:
    """Check only source/templates; do not construct an application or connect."""

    issues: list[str] = []
    compose_path = PROJECT_ROOT / "compose.yaml"
    compose = yaml.load(compose_path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    services = compose.get("services", {})
    backend = services.get("backend", {})
    worker = services.get("worker", {})
    backend_command = tuple(str(item) for item in backend.get("command", ()))
    worker_command = tuple(str(item) for item in worker.get("command", ()))
    if backend_command != EXPECTED_BACKEND_COMMAND:
        issues.append("Compose backend command is not health-only backend.app.main:app")
    if worker_command != EXPECTED_WORKER_COMMAND:
        issues.append("Compose worker command is not backend.app.worker")

    environment = compose.get("x-backend-environment", {})
    expected_defaults = {
        "RECPRO_AUTH_ENABLED": False,
        "RECPRO_PRODUCTION_HTTP_ENABLED": False,
        "RECPRO_G4_HTTP_ENABLED": False,
        "RECPRO_G5_INTERACTION_HTTP_ENABLED": False,
        "RECPRO_WORKER_ENABLED": False,
        "RECPRO_LLM_PROVIDER": "mock",
    }
    for key, expected in expected_defaults.items():
        actual = environment.get(key)
        if expected is False and not _default_false(actual):
            issues.append(f"Compose default {key} is not false")
        if expected == "mock" and actual != "${RECPRO_LLM_PROVIDER:-mock}":
            issues.append("Compose default RECPRO_LLM_PROVIDER is not mock")
    if environment.get("RECPRO_WORKER_MODE") != "${RECPRO_WORKER_MODE:-disabled}":
        issues.append("Compose default RECPRO_WORKER_MODE is not disabled")

    for env_name in (".env.compose.example", ".env.host.example"):
        values = parse_env_file(PROJECT_ROOT / env_name)
        for key in (
            "RECPRO_AUTH_ENABLED",
            "RECPRO_PRODUCTION_HTTP_ENABLED",
            "RECPRO_G4_HTTP_ENABLED",
            "RECPRO_G5_INTERACTION_HTTP_ENABLED",
            "RECPRO_WORKER_ENABLED",
        ):
            if values.get(key) != "false":
                issues.append(f"{env_name} {key} is not false")
        if values.get("RECPRO_WORKER_MODE") != "disabled":
            issues.append(f"{env_name} RECPRO_WORKER_MODE is not disabled")
        if values.get("RECPRO_LLM_PROVIDER") != "mock":
            issues.append(f"{env_name} RECPRO_LLM_PROVIDER is not mock")

    app_source = (PROJECT_ROOT / "frontend/src/App.vue").read_text(encoding="utf-8")
    if 'import.meta.env.VITE_G5_INTERACTION_ENABLED === "true"' not in app_source:
        issues.append("frontend G5 interaction gate is not an explicit true-only check")
    main_source = (PROJECT_ROOT / "backend/app/main.py").read_text(encoding="utf-8")
    if "app = create_app()" not in main_source:
        issues.append("default FastAPI app is not the health-only composition root")
    if "feedback_api_enabled=True" in main_source:
        issues.append("default FastAPI app unexpectedly enables feedback API")

    return {
        "status": "PASS" if not issues else "FAIL",
        "issues": issues,
        "checked": [
            "compose.yaml",
            ".env.compose.example",
            ".env.host.example",
            "frontend/src/App.vue",
            "backend/app/main.py",
        ],
    }


def tracked_file_manifest() -> dict[str, Any]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
    )
    paths = [Path(value) for value in result.stdout.decode("utf-8").split("\0") if value]
    files: list[dict[str, Any]] = []
    for relative in paths:
        path = PROJECT_ROOT / relative
        if not path.is_file() or path.is_symlink():
            continue
        files.append(
            {
                "path": relative.as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    canonical = "\n".join(f"{item['path']}\0{item['sha256']}" for item in files).encode()
    return {
        "file_count": len(files),
        "root_sha256": hashlib.sha256(canonical).hexdigest(),
        "files": files,
    }


def _tail(value: str, limit: int = 6000) -> str:
    return value if len(value) <= limit else value[-limit:]


def run_command(
    *,
    label: str,
    command: Sequence[str],
    environment: Mapping[str, str] | None = None,
    timeout_seconds: float = 900.0,
) -> dict[str, Any]:
    started = time.monotonic()
    merged = os.environ.copy()
    if environment:
        merged.update(environment)
    try:
        result = subprocess.run(
            list(command),
            cwd=PROJECT_ROOT,
            env=merged,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        status = "PASS" if result.returncode == 0 else "FAIL"
        return {
            "label": label,
            "status": status,
            "command": list(command),
            "exit_code": result.returncode,
            "duration_ms": round((time.monotonic() - started) * 1000, 2),
            "stdout_tail": _tail(result.stdout),
            "stderr_tail": _tail(result.stderr),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "label": label,
            "status": "FAIL",
            "command": list(command),
            "exit_code": None,
            "duration_ms": round((time.monotonic() - started) * 1000, 2),
            "stdout_tail": _tail((exc.stdout or "") if isinstance(exc.stdout, str) else ""),
            "stderr_tail": "command timed out",
        }
    except OSError as exc:
        return {
            "label": label,
            "status": "FAIL",
            "command": list(command),
            "exit_code": None,
            "duration_ms": round((time.monotonic() - started) * 1000, 2),
            "stdout_tail": "",
            "stderr_tail": str(exc),
        }


def inspect_frontend_dist(path: Path) -> dict[str, Any]:
    if not path.is_dir() or path.is_symlink():
        return {"status": "FAIL", "error": "frontend build directory is not a plain directory"}
    index = path / "index.html"
    if not index.is_file() or index.is_symlink():
        return {"status": "FAIL", "error": "frontend build is missing a plain index.html"}
    files: list[dict[str, Any]] = []
    for child in sorted(path.rglob("*")):
        if child.is_file() and not child.is_symlink():
            files.append(
                {
                    "path": child.relative_to(path).as_posix(),
                    "bytes": child.stat().st_size,
                    "sha256": sha256_file(child),
                }
            )
    return {
        "status": "PASS",
        "path": path.relative_to(PROJECT_ROOT).as_posix(),
        "file_count": len(files),
        "files": files,
    }


def inspect_backend_image(docker_cli: str, image: str) -> dict[str, Any]:
    result = subprocess.run(
        [docker_cli, "image", "inspect", "--format", "{{json .}}", image],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return {
            "status": "FAIL",
            "image": image,
            "error": _tail(result.stderr),
        }
    try:
        metadata = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"status": "FAIL", "image": image, "error": "docker inspect was not JSON"}
    config = metadata.get("Config", {})
    command = tuple(config.get("Cmd") or ())
    issues: list[str] = []
    if command != EXPECTED_BACKEND_COMMAND:
        issues.append("backend image command is not health-only backend.app.main:app")
    if config.get("User") != "recpro":
        issues.append("backend image does not run as recpro")
    return {
        "status": "PASS" if not issues else "FAIL",
        "image": image,
        "image_id": metadata.get("Id"),
        "repo_digests": metadata.get("RepoDigests", []),
        "created": metadata.get("Created"),
        "user": config.get("User"),
        "command": list(command),
        "issues": issues,
    }


def build_report(
    *,
    run_id: str,
    frontend_run_id: str,
    frontend_path: Path,
    backend_image: str | None,
    docker_cli: str,
    python_executable: str,
    command_results: list[dict[str, Any]],
    static_defaults: dict[str, Any],
    frontend_dist: dict[str, Any],
    backend_image_report: dict[str, Any],
    git_commit: str,
    git_status: str,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    failed_checks = [
        item["label"] for item in command_results if item.get("status") != "PASS"
    ]
    if static_defaults.get("status") != "PASS":
        failed_checks.append("fail_closed_defaults")
    if frontend_dist.get("status") != "PASS":
        failed_checks.append("frontend_dist")
    if backend_image and backend_image_report.get("status") != "PASS":
        failed_checks.append("backend_image")
    blockers = list(DEFAULT_BLOCKERS)
    if not backend_image:
        blockers.append(
            {
                "code": "BACKEND_IMAGE_NOT_SUPPLIED",
                "message": "No local backend image tag was supplied for inspection.",
            }
        )
    status = "FAIL" if failed_checks else "PASS_WITH_BLOCKERS"
    return {
        "schema_version": "g8-release-preflight-v1",
        "run_id": run_id,
        "frontend_run_id": frontend_run_id,
        "status": status,
        "release_candidate_ready": False,
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "git": {
            "commit": git_commit,
            "status_before_report": git_status,
        },
        "runtime": {
            "python": python_executable,
            "docker_cli": docker_cli,
            "backend_image": backend_image,
        },
        "checks": {
            "commands": command_results,
            "fail_closed_defaults": static_defaults,
            "frontend_dist": frontend_dist,
            "backend_image": backend_image_report,
        },
        "tracked_source_manifest": manifest,
        "blockers": blockers,
        "safety": {
            "database_reads": 0,
            "database_writes": 0,
            "neo4j_reads": 0,
            "neo4j_writes": 0,
            "chroma_reads": 0,
            "chroma_writes": 0,
            "external_llm_requests": 0,
            "files_deleted": 0,
            "database_physical_deletes": 0,
            "artifacts_overwritten": 0,
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--frontend-run-id", required=True)
    parser.add_argument("--python", default=sys.executable, dest="python_executable")
    parser.add_argument("--npm", default="npm")
    parser.add_argument("--docker-cli", default="docker")
    parser.add_argument("--backend-image", default="")
    parser.add_argument("--timeout-seconds", type=float, default=900.0)
    args = parser.parse_args(argv)

    try:
        run_id = validate_run_id(args.run_id)
        frontend_run_id = validate_run_id(args.frontend_run_id)
        if run_id == frontend_run_id:
            raise ValueError("release and frontend run IDs must be different")
        artifact_dir = resolve_inside_project(
            PROJECT_ROOT / "artifacts" / "verification" / "g8" / run_id,
            label="artifact directory",
        )
        if artifact_dir.exists():
            raise ValueError(f"artifact directory already exists: {artifact_dir}")
        frontend_path = resolve_inside_project(
            PROJECT_ROOT / "frontend" / "dist" / frontend_run_id,
            label="frontend build directory",
        )
        for relative in REQUIRED_FILES:
            path = PROJECT_ROOT / relative
            if not path.is_file() or path.is_symlink():
                raise ValueError(f"required release file is missing or unsafe: {relative}")
    except ValueError as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False))
        return 2

    git_status_result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    git_status = git_status_result.stdout.strip()
    git_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    command_results: list[dict[str, Any]] = []
    command_results.append(
        {
            "label": "git_clean_before_report",
            "status": "PASS" if not git_status else "FAIL",
            "command": ["git", "status", "--porcelain", "--untracked-files=all"],
            "exit_code": 0,
            "duration_ms": 0,
            "stdout_tail": git_status,
            "stderr_tail": "",
        }
    )
    python = args.python_executable
    static_commands = [
        ("contracts", [python, "-m", "scripts.validate_contracts", "--root", "."]),
        ("docs", [python, "-m", "scripts.validate_docs", "--root", "."]),
        ("architecture", [python, "scripts/architecture_guard.py", "--root", "."]),
        ("safety", [python, "scripts/safety_scan.py", "--root", "."]),
        ("g1_tests", [python, "-m", "unittest", "discover", "-s", "tests/g1", "-t", "tests", "-p", "test_*.py"]),
        ("g4_tests", [python, "-m", "unittest", "discover", "-s", "tests/g4", "-t", "tests", "-p", "test_*.py"]),
        ("g5_tests", [python, "-m", "unittest", "discover", "-s", "tests/g5", "-t", "tests", "-p", "test_*.py"]),
        ("g7_tests", [python, "-m", "unittest", "discover", "-s", "tests/g7", "-t", "tests", "-p", "test_*.py"]),
        ("g8_tests", [python, "-m", "unittest", "discover", "-s", "tests/g8", "-t", "tests", "-p", "test_*.py"]),
        ("frontend_tests", [args.npm, "--prefix", "frontend", "test"]),
    ]
    for label, command in static_commands:
        command_results.append(
            run_command(label=label, command=command, timeout_seconds=args.timeout_seconds)
        )
    command_results.append(
        run_command(
            label="frontend_build",
            command=[args.npm, "--prefix", "frontend", "run", "build"],
            environment={"RECPRO_BUILD_RUN_ID": frontend_run_id},
            timeout_seconds=args.timeout_seconds,
        )
    )

    static_defaults = inspect_fail_closed_defaults()
    frontend_dist = inspect_frontend_dist(frontend_path)
    backend_image_report: dict[str, Any] = {
        "status": "NOT_CHECKED",
        "image": args.backend_image or None,
    }
    if args.backend_image:
        try:
            backend_image_report = inspect_backend_image(args.docker_cli, args.backend_image)
        except OSError as exc:
            backend_image_report = {
                "status": "FAIL",
                "image": args.backend_image,
                "error": str(exc),
            }
    manifest = tracked_file_manifest()
    report = build_report(
        run_id=run_id,
        frontend_run_id=frontend_run_id,
        frontend_path=frontend_path,
        backend_image=args.backend_image or None,
        docker_cli=args.docker_cli,
        python_executable=python,
        command_results=command_results,
        static_defaults=static_defaults,
        frontend_dist=frontend_dist,
        backend_image_report=backend_image_report,
        git_commit=git_commit,
        git_status=git_status,
        manifest=manifest,
    )

    artifact_dir.mkdir(parents=True, exist_ok=False)
    report_path = artifact_dir / "release-preflight.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": report["status"], "path": report_path.relative_to(PROJECT_ROOT).as_posix(), "blocker_count": len(report["blockers"])}, ensure_ascii=False))
    return 0 if report["status"] != "FAIL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
