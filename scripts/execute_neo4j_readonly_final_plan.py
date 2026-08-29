#!/usr/bin/env python3
"""Build and accept a fresh read-only Neo4j Community replica without deletion."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import tarfile
import time
from typing import Any, Mapping, Sequence

from scripts.build_neo4j_readonly_replica_plan import IMAGE, PROJECT_ROOT, V1_DIR, V2_DIR
from scripts.execute_neo4j_readonly_replica_plan import (
    DOCKER,
    EVIDENCE_ROOT,
    RUN_ID_PATTERN,
    _append_graph,
    _canonical_hash,
    _client,
    _read_access_settings,
)
from scripts.import_book_graph import cypher_count_graph_version, sha256_bytes
from scripts.validate_runtime_env import read_env


COMPOSE_FILE = PROJECT_ROOT / "compose.neo4j-readonly-final.yaml"
SECRET_FILE = PROJECT_ROOT / ".env.neo4j-readonly-final.local"
PROJECT_NAME = "recpro-neo4j-readonly-final-20260829"
SERVICE_NAME = "neo4j-readonly-final"
CONTAINER_NAME = f"{PROJECT_NAME}-{SERVICE_NAME}-1"
DATA_VOLUME = "recpro_neo4j_readonly_final_20260829_data"
LOG_VOLUME = "recpro_neo4j_readonly_final_20260829_logs"
HTTP_PORT = 62948
BOLT_PORT = 62968
CONFIG_PATH = "/var/lib/neo4j/conf/neo4j.conf"
WRITABLE_LINE = b"server.databases.writable=neo4j\n"
SOURCE_BASELINE = {"v1": (63388, 191865), "v2": (78129, 206848)}


def dry_run_report() -> dict[str, object]:
    return {
        "schema_version": "neo4j-readonly-final-dry-run-v1",
        "mode": "NO_CONNECTION_NO_WRITE_DRY_RUN",
        "new_containers": 1,
        "new_volumes": 2,
        "new_secret_files": 1,
        "controlled_container_stops_max": 2,
        "controlled_container_starts_after_create_max": 2,
        "graceful_stop_timeout_seconds": 600,
        "config_replacements_max": 2,
        "replica_nodes_max": 141517,
        "replica_relationships_max": 398713,
        "container_deletions": 0,
        "volume_deletions": 0,
        "file_deletions": 0,
        "database_deletions": 0,
        "source_graph_writes": 0,
        "deepseek_requests": 0,
        "docker_connections": 0,
        "database_connections": 0,
    }


def _load_plan(path: Path, *, plan_id: str, plan_hash: str) -> dict[str, Any]:
    resolved = path.resolve(strict=True)
    resolved.relative_to(PROJECT_ROOT)
    plan = json.loads(resolved.read_text(encoding="utf-8"))
    if plan.get("plan_id") != plan_id or plan.get("plan_hash") != plan_hash:
        raise ValueError("approved final replica plan identity does not match")
    if plan.get("schema_version") != "recpro-neo4j-readonly-final-plan-v1":
        raise ValueError("unsupported final replica plan schema")
    if _canonical_hash(plan) != plan_hash:
        raise ValueError("final replica canonical hash does not match")
    zero_keys = (
        "file_deletions", "database_deletions", "container_deletions",
        "volume_deletions", "failed_replica_changes", "source_graph_writes",
        "deepseek_requests",
    )
    safety = plan.get("safety", {})
    if any(safety.get(key) != 0 for key in zero_keys):
        raise ValueError("final replica safety boundary is incomplete")
    return plan


def _verify_commit_and_hashes(plan: Mapping[str, Any]) -> None:
    reviewed = str(plan["git_commit"])
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", reviewed, "HEAD"],
        cwd=PROJECT_ROOT, check=True,
    )
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=PROJECT_ROOT, check=True, capture_output=True, text=True,
    ).stdout.strip()
    if dirty:
        raise ValueError("tracked worktree must be clean before final replica apply")
    hashes = plan.get("input_hashes")
    if not isinstance(hashes, Mapping):
        raise ValueError("final replica input hashes are missing")
    for relative, expected in hashes.items():
        candidate = (PROJECT_ROOT / str(relative)).resolve(strict=True)
        candidate.relative_to(PROJECT_ROOT)
        if sha256_bytes(candidate.read_bytes()) != expected:
            raise ValueError(f"final replica input hash drift: {relative}")


def _docker(args: Sequence[str], *, input_bytes: bytes | None = None) -> bytes:
    return subprocess.run(
        [str(DOCKER), *args], cwd=PROJECT_ROOT, input=input_bytes,
        check=True, capture_output=True,
    ).stdout


def _absence_guard() -> None:
    if not DOCKER.is_file():
        raise ValueError("approved Docker executable is unavailable")
    if SECRET_FILE.exists():
        raise ValueError("final replica credential file already exists")
    containers = _docker([
        "ps", "-a", "--quiet", "--filter", f"label=com.docker.compose.project={PROJECT_NAME}",
    ])
    if containers.strip():
        raise ValueError("final replica Compose project already exists")
    for volume in (DATA_VOLUME, LOG_VOLUME):
        inspected = subprocess.run(
            [str(DOCKER), "volume", "inspect", volume], cwd=PROJECT_ROOT,
            capture_output=True,
        )
        if inspected.returncode == 0:
            raise ValueError("final replica approved volume already exists")


def _write_secret(password: str) -> None:
    content = (
        f"RECPRO_FINAL_NEO4J_PROJECT_NAME={PROJECT_NAME}\n"
        f"RECPRO_FINAL_NEO4J_DATA_VOLUME={DATA_VOLUME}\n"
        f"RECPRO_FINAL_NEO4J_LOG_VOLUME={LOG_VOLUME}\n"
        f"RECPRO_FINAL_NEO4J_HTTP_HOST_PORT={HTTP_PORT}\n"
        f"RECPRO_FINAL_NEO4J_BOLT_HOST_PORT={BOLT_PORT}\n"
        f"RECPRO_FINAL_NEO4J_PASSWORD={password}\n"
    )
    descriptor = os.open(SECRET_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(content)


def _inspect_container() -> dict[str, Any]:
    payload = json.loads(_docker(["inspect", CONTAINER_NAME]))
    if not isinstance(payload, list) or len(payload) != 1:
        raise ValueError("final replica container identity is ambiguous")
    return payload[0]


def _assert_container_identity(*, expected_running: bool) -> dict[str, Any]:
    inspected = _inspect_container()
    if inspected.get("Config", {}).get("Image") != IMAGE:
        raise ValueError("final replica image differs from approval")
    mounts = {item.get("Destination"): item.get("Name") for item in inspected.get("Mounts", [])}
    if mounts != {"/data": DATA_VOLUME, "/logs": LOG_VOLUME}:
        raise ValueError("final replica mounts differ from the two approved volumes")
    running = bool(inspected.get("State", {}).get("Running"))
    if running != expected_running:
        raise ValueError("final replica running state differs from expectation")
    return inspected


def _tar_config(config: bytes) -> bytes:
    stream = BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        entry = tarfile.TarInfo("neo4j.conf")
        entry.uid = 7474
        entry.gid = 7474
        entry.mode = 0o600
        entry.mtime = 0
        entry.size = len(config)
        archive.addfile(entry, BytesIO(config))
    return stream.getvalue()


def _replace_config(config: bytes) -> None:
    _docker(
        ["cp", "-a", "-", f"{CONTAINER_NAME}:/var/lib/neo4j/conf"],
        input_bytes=_tar_config(config),
    )
    if _read_config() != config:
        raise RuntimeError("final replica configuration replacement did not verify")


def _read_config() -> bytes:
    payload = _docker(["cp", f"{CONTAINER_NAME}:{CONFIG_PATH}", "-"])
    with tarfile.open(fileobj=BytesIO(payload), mode="r:") as archive:
        files = [member for member in archive.getmembers() if member.isfile()]
        if len(files) != 1:
            raise RuntimeError("final replica configuration archive is ambiguous")
        extracted = archive.extractfile(files[0])
        if extracted is None:
            raise RuntimeError("final replica configuration archive is unreadable")
        return extracted.read()


def _wait_database(password: str, *, access: str, status: str, timeout: float = 240.0) -> None:
    system = _client(HTTP_PORT, "neo4j", password, database="system")
    deadline = time.monotonic() + timeout
    last: list[object] | None = None
    while time.monotonic() < deadline:
        try:
            rows = system.run(
                "SHOW DATABASES YIELD name, access, currentStatus "
                "WHERE name = 'neo4j' RETURN name, access, currentStatus"
            )
            last = rows[0]["row"] if rows else None
            if last == ["neo4j", access, status]:
                return
        except Exception:
            pass
        time.sleep(2.0)
    raise TimeoutError(f"final replica database state timeout; last={last!r}")


def _stop_gracefully(timeout_seconds: int) -> dict[str, object]:
    started = time.monotonic()
    _docker(["stop", "--time", str(timeout_seconds), CONTAINER_NAME])
    elapsed = time.monotonic() - started
    inspected = _assert_container_identity(expected_running=False)
    state = inspected.get("State", {})
    if state.get("ExitCode") != 0 or state.get("OOMKilled") is not False:
        raise RuntimeError("final replica did not stop cleanly")
    return {"timeout_seconds": timeout_seconds, "elapsed_seconds": round(elapsed, 3), "exit_code": 0}


def _start() -> None:
    _docker(["start", CONTAINER_NAME])


def _wait_container_healthy(timeout_seconds: float = 120.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last = "unknown"
    while time.monotonic() < deadline:
        inspected = _assert_container_identity(expected_running=True)
        last = str(inspected.get("State", {}).get("Health", {}).get("Status", "missing"))
        if last == "healthy":
            return inspected
        time.sleep(2.0)
    raise TimeoutError(f"final replica container health timeout; last={last}")


def _source_client(path: Path) -> tuple[Any, dict[str, tuple[int, int]]]:
    values = read_env(path.resolve(strict=True))
    required = (
        "RECPRO_LIBRARY_NEO4J_HTTP_HOST_PORT", "RECPRO_NEO4J_ADMIN_USER",
        "RECPRO_NEO4J_ADMIN_PASSWORD",
    )
    if any(not values.get(key) for key in required):
        raise ValueError("source Neo4j environment is incomplete")
    client = _client(
        int(values["RECPRO_LIBRARY_NEO4J_HTTP_HOST_PORT"]),
        values["RECPRO_NEO4J_ADMIN_USER"], values["RECPRO_NEO4J_ADMIN_PASSWORD"],
    )
    counts = {
        "v1": cypher_count_graph_version(client, "lib-books-v1-20260810"),
        "v2": cypher_count_graph_version(client, "lib-books-v2-20260828"),
    }
    return client, counts


def apply_plan(*, plan: Mapping[str, Any], source_env_file: Path, run_id: str) -> dict[str, object]:
    if RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise ValueError("final replica run id has an unsafe format")
    _verify_commit_and_hashes(plan)
    _absence_guard()
    source, source_before = _source_client(source_env_file)
    if source_before != SOURCE_BASELINE:
        raise ValueError("source graph differs from the frozen final baseline")
    password = secrets.token_urlsafe(36)
    _write_secret(password)
    environment = os.environ.copy()
    environment.update(read_env(SECRET_FILE))
    subprocess.run(
        [str(DOCKER), "compose", "-f", str(COMPOSE_FILE), "--env-file", str(SECRET_FILE),
         "up", "-d", SERVICE_NAME],
        cwd=PROJECT_ROOT, env=environment, check=True, capture_output=True,
    )
    _wait_database(password, access="read-only", status="offline")
    _assert_container_identity(expected_running=True)
    original_config = _read_config()
    if b"server.databases.default_to_read_only=true" not in original_config:
        raise ValueError("final replica generated config lacks the read-only default")
    if WRITABLE_LINE.strip() in {line.strip() for line in original_config.splitlines()}:
        raise ValueError("final replica generated config unexpectedly permits writes")
    original_hash = sha256(original_config).hexdigest()

    initial_stop = _stop_gracefully(120)
    writable_config = original_config + (b"" if original_config.endswith(b"\n") else b"\n") + WRITABLE_LINE
    _replace_config(writable_config)
    _start()
    _wait_database(password, access="read-write", status="online")
    target = _client(HTTP_PORT, "neo4j", password)
    import_error: BaseException | None = None
    imported: dict[str, dict[str, int]] = {}
    try:
        empty = {
            "v1": cypher_count_graph_version(target, "lib-books-v1-20260810"),
            "v2": cypher_count_graph_version(target, "lib-books-v2-20260828"),
        }
        if empty != {"v1": (0, 0), "v2": (0, 0)}:
            raise ValueError("final replica expected a new empty graph")
        imported["v1"] = _append_graph(target, V1_DIR)
        imported["v2"] = _append_graph(target, V2_DIR)
        before_stop = {
            "v1": cypher_count_graph_version(target, "lib-books-v1-20260810"),
            "v2": cypher_count_graph_version(target, "lib-books-v2-20260828"),
        }
        if before_stop != SOURCE_BASELINE:
            raise RuntimeError("final replica import counts differ before graceful stop")
    except BaseException as exc:
        import_error = exc
    stop_error: BaseException | None = None
    final_stop: dict[str, object] = {}
    try:
        final_stop = _stop_gracefully(600)
    except BaseException as exc:
        stop_error = exc
    if _inspect_container().get("State", {}).get("Running"):
        raise RuntimeError("final replica remained running after graceful stop failure")
    _replace_config(original_config)
    _start()
    _wait_database(password, access="read-only", status="online")
    if stop_error is not None:
        raise stop_error
    if import_error is not None:
        raise import_error

    if sha256(_read_config()).hexdigest() != original_hash:
        raise RuntimeError("final replica original configuration was not restored")
    settings = _read_access_settings(target)
    if settings != {
        "server.databases.default_to_read_only": "true",
        "server.databases.writable": "",
    }:
        raise RuntimeError("final replica did not finish read-only")
    replica_counts = {
        "v1": cypher_count_graph_version(target, "lib-books-v1-20260810"),
        "v2": cypher_count_graph_version(target, "lib-books-v2-20260828"),
    }
    source_after = {
        "v1": cypher_count_graph_version(source, "lib-books-v1-20260810"),
        "v2": cypher_count_graph_version(source, "lib-books-v2-20260828"),
    }
    if replica_counts != SOURCE_BASELINE or source_after != source_before:
        raise RuntimeError("final replica reconciliation failed")
    inspected = _wait_container_healthy()
    report: dict[str, object] = {
        "schema_version": "neo4j-readonly-final-acceptance-v1",
        "status": "PASS",
        "run_id": run_id,
        "plan_id": plan["plan_id"],
        "plan_hash": plan["plan_hash"],
        "container_id": inspected["Id"],
        "data_volume": DATA_VOLUME,
        "log_volume": LOG_VOLUME,
        "imported": imported,
        "replica_counts": replica_counts,
        "source_before": source_before,
        "source_after": source_after,
        "access_settings": settings,
        "original_config_sha256": original_hash,
        "stops": {"initial": initial_stop, "post_import": final_stop},
        "safety": plan["safety"],
        "generated_at": datetime.now(UTC).isoformat(),
    }
    evidence_dir = EVIDENCE_ROOT / run_id
    evidence_dir.mkdir(parents=True, exist_ok=False)
    with (evidence_dir / "acceptance.json").open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--plan-id")
    parser.add_argument("--approved-plan-hash")
    parser.add_argument("--source-env-file", type=Path, default=PROJECT_ROOT / ".env.user-secrets")
    parser.add_argument("--run-id", default="neo4j-readonly-final-20260829-001")
    args = parser.parse_args(argv)
    if not args.apply:
        print(json.dumps(dry_run_report(), ensure_ascii=False, indent=2))
        return 0
    if not args.plan or not args.plan_id or not args.approved_plan_hash:
        raise ValueError("final apply requires exact plan path, id, and hash")
    plan = _load_plan(args.plan, plan_id=args.plan_id, plan_hash=args.approved_plan_hash)
    print(json.dumps(apply_plan(
        plan=plan, source_env_file=args.source_env_file, run_id=args.run_id,
    ), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
