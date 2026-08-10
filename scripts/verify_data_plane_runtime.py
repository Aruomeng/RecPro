"""Read-only MySQL/Neo4j Docker health and identity verification.

The verifier never starts, stops, migrates, resets, or cleans a service.  It
only inspects the already-running Compose project, performs a MySQL SELECT and
two Neo4j count queries, and writes a new evidence report with exclusive file
creation.  It is safe to run before book import to prove that the data plane is
available without changing existing facts.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Sequence

from scripts.validate_runtime_env import read_env, validate_compose


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
DEFAULT_DOCKER = Path("/Applications/编程/Docker.app/Contents/Resources/bin/docker")


def validate_run_id(value: str) -> str:
    if RUN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("run id must use 3-64 safe characters")
    return value


def resolve_repository_path(value: str | Path, *, label: str) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError(f"{label} must resolve inside the repository") from exc
    return resolved


def _relative(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


def _run(command: Sequence[str], *, cwd: Path = PROJECT_ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def parse_service_state(output: str) -> dict[str, dict[str, str]]:
    services: dict[str, dict[str, str]] = {}
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        fields = line.split("\t", maxsplit=2)
        if len(fields) == 1:
            service, health, state = fields[0], "", ""
        elif len(fields) == 2:
            service, health, state = fields[0], fields[1], ""
        else:
            service, health, state = fields
        services[service] = {"health": health, "state": state}
    return services


def parse_count_output(output: str) -> int:
    values = [line.strip() for line in output.splitlines() if line.strip()]
    for value in reversed(values):
        if value.isdigit():
            return int(value)
    raise ValueError("database count output did not contain a non-negative integer")


def build_blocker(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def execute(
    *,
    run_id: str,
    env_file: Path,
    docker_bin: Path,
    git_commit: str,
    git_worktree_dirty: bool,
) -> dict[str, Any]:
    validate_run_id(run_id)
    env_path = resolve_repository_path(env_file, label="compose environment file")
    if not env_path.is_file():
        raise ValueError("compose environment file is missing")
    docker_path = docker_bin
    if not docker_path.is_absolute():
        docker_path = Path(str(docker_path))
    if not docker_path.is_file():
        raise ValueError(f"Docker executable is missing: {docker_path}")

    values = read_env(env_path)
    env_issues = validate_compose(values)
    blockers: list[dict[str, str]] = [
        build_blocker("COMPOSE_ENV_INVALID", issue) for issue in env_issues
    ]
    compose_base = [str(docker_path), "compose", "--env-file", str(env_path)]
    service_summary: dict[str, dict[str, str]] = {}
    mysql: dict[str, Any] = {"status": "NOT_CHECKED"}
    neo4j: dict[str, Any] = {"status": "NOT_CHECKED"}
    if not env_issues:
        try:
            ps_result = _run([*compose_base, "ps", "--format", "{{.Service}}\t{{.Health}}\t{{.State}}"])
            service_summary = parse_service_state(ps_result.stdout)
        except subprocess.CalledProcessError as exc:
            _append_unique(blockers, "COMPOSE_PS_FAILED", "docker compose ps could not inspect the project")
            service_summary = {"command_error": {"health": "unknown", "state": str(exc.returncode)}}

        for service_name in ("mysql", "neo4j"):
            service = service_summary.get(service_name)
            if not service or service.get("health") != "healthy":
                _append_unique(
                    blockers,
                    f"{service_name.upper()}_NOT_HEALTHY",
                    f"Compose service {service_name} is not healthy",
                )

        if service_summary.get("mysql", {}).get("health") == "healthy":
            try:
                mysql_result = _run(
                    [
                        *compose_base,
                        "exec",
                        "-T",
                        "mysql",
                        "sh",
                        "-c",
                        "mysql --protocol=socket --user=\"$RECPRO_MYSQL_RUNTIME_USER\" "
                        "--password=\"$RECPRO_MYSQL_RUNTIME_PASSWORD\" "
                        "--database=\"$MYSQL_DATABASE\" --batch --skip-column-names "
                        "-e \"SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE();\"",
                    ]
                )
                mysql = {
                    "status": "UP",
                    "table_count": parse_count_output(mysql_result.stdout),
                    "query_type": "SELECT_ONLY",
                }
            except (OSError, subprocess.CalledProcessError, ValueError):
                mysql = {"status": "DOWN", "query_type": "SELECT_ONLY"}
                _append_unique(blockers, "MYSQL_READ_ONLY_QUERY_FAILED", "MySQL read-only identity query failed")

        if service_summary.get("neo4j", {}).get("health") == "healthy":
            try:
                node_result = _run(
                    [
                        *compose_base,
                        "exec",
                        "-T",
                        "neo4j",
                        "sh",
                        "-c",
                        "cypher-shell --address neo4j://127.0.0.1:7687 "
                        "--username \"$RECPRO_NEO4J_USER\" --password \"$RECPRO_NEO4J_PASSWORD\" "
                        "'MATCH (n) RETURN count(n);'",
                    ]
                )
                relationship_result = _run(
                    [
                        *compose_base,
                        "exec",
                        "-T",
                        "neo4j",
                        "sh",
                        "-c",
                        "cypher-shell --address neo4j://127.0.0.1:7687 "
                        "--username \"$RECPRO_NEO4J_USER\" --password \"$RECPRO_NEO4J_PASSWORD\" "
                        "'MATCH ()-[r]->() RETURN count(r);'",
                    ]
                )
                neo4j = {
                    "status": "UP",
                    "node_count": parse_count_output(node_result.stdout),
                    "relationship_count": parse_count_output(relationship_result.stdout),
                    "query_type": "READ_ONLY_COUNT",
                }
            except (OSError, subprocess.CalledProcessError, ValueError):
                neo4j = {"status": "DOWN", "query_type": "READ_ONLY_COUNT"}
                _append_unique(blockers, "NEO4J_READ_ONLY_QUERY_FAILED", "Neo4j read-only count query failed")

    report = {
        "schema_version": "data-plane-runtime-report-v1",
        "status": "PASS_WITH_BLOCKERS" if blockers else "PASS",
        "verified_at": datetime.now(UTC).isoformat(),
        "git_commit": git_commit,
        "git_worktree_dirty": git_worktree_dirty,
        "compose_project": values.get("COMPOSE_PROJECT_NAME"),
        "env_file": _relative(env_path),
        "services": service_summary,
        "mysql": mysql,
        "neo4j": neo4j,
        "blockers": blockers,
        "safety": {
            "mysql_queries": 1 if mysql.get("status") == "UP" else 0,
            "neo4j_queries": 2 if neo4j.get("status") == "UP" else 0,
            "database_writes": 0,
            "expected_delete_count": 0,
            "actual_delete_count": 0,
            "service_start_stop_actions": 0,
        },
    }
    evidence_dir = PROJECT_ROOT / "artifacts/verification/data-plane" / run_id
    evidence_dir.mkdir(parents=True, exist_ok=False)
    output_path = evidence_dir / "runtime.json"
    with output_path.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return report


def _append_unique(blockers: list[dict[str, str]], code: str, message: str) -> None:
    if not any(item["code"] == code for item in blockers):
        blockers.append(build_blocker(code, message))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.compose")
    parser.add_argument("--docker-bin", type=Path, default=DEFAULT_DOCKER)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        git_commit = _run(
            ["git", "rev-parse", "HEAD"],
        ).stdout.strip()
        git_status = _run(["git", "status", "--porcelain"]).stdout.strip()
        report = execute(
            run_id=args.run_id,
            env_file=args.env_file,
            docker_bin=args.docker_bin,
            git_commit=git_commit,
            git_worktree_dirty=bool(git_status),
        )
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"[FAIL] data-plane verification did not complete: {type(exc).__name__}: {exc}")
        return 1
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
