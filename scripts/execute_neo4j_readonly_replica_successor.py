#!/usr/bin/env python3
"""Resume the Neo4j Community replica from the frozen partial state.

The Community image cannot use ``dbms.setConfigValue``.  This executor uses
the already-created container only: it temporarily replaces its generated
configuration with an in-memory, hash-bound writable variant, restarts the
same container, appends the frozen graph artifacts, restores the exact
original configuration bytes, and restarts into read-only mode.  It never
removes or recreates a container, volume, file, database, node, relationship,
or constraint.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re
import subprocess
import tarfile
import time
from typing import Any, Mapping, Sequence

from scripts.build_neo4j_readonly_replica_plan import (
    HTTP_PORT,
    IMAGE,
    PROJECT_NAME,
    PROJECT_ROOT,
    V1_DIR,
    V2_DIR,
    VOLUME_NAME,
)
from scripts.execute_neo4j_readonly_replica_plan import (
    DOCKER,
    EVIDENCE_ROOT,
    RUN_ID_PATTERN,
    SECRET_FILE,
    _append_graph,
    _canonical_hash,
    _client,
    _read_access_settings,
)
from scripts.import_book_graph import cypher_count_graph_version, sha256_bytes
from scripts.validate_runtime_env import read_env


CONTAINER_NAME = f"{PROJECT_NAME}-neo4j-readonly-1"
CONFIG_PATH = "/var/lib/neo4j/conf/neo4j.conf"
WRITABLE_LINE = b"server.databases.writable=neo4j\n"
SOURCE_BASELINE = {"v1": (63388, 191865), "v2": (78129, 206848)}


def dry_run_report() -> dict[str, object]:
    return {
        "schema_version": "neo4j-readonly-replica-successor-dry-run-v1",
        "mode": "NO_CONNECTION_NO_WRITE_DRY_RUN",
        "existing_container_restarts_max": 2,
        "container_config_replacements_max": 2,
        "replica_nodes_max": 141517,
        "replica_relationships_max": 398713,
        "new_containers": 0,
        "new_volumes": 0,
        "new_secret_files": 0,
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
    document = json.loads(resolved.read_text(encoding="utf-8"))
    if document.get("plan_id") != plan_id or document.get("plan_hash") != plan_hash:
        raise ValueError("approved replica successor identity does not match")
    if document.get("schema_version") != "recpro-neo4j-readonly-replica-successor-plan-v1":
        raise ValueError("unsupported replica successor schema")
    if _canonical_hash(document) != plan_hash:
        raise ValueError("replica successor canonical hash does not match")
    safety = document.get("safety", {})
    required_zero = (
        "file_deletions", "database_deletions", "container_deletions",
        "volume_deletions", "new_containers", "new_volumes",
        "new_secret_files", "source_graph_writes", "deepseek_requests",
    )
    if any(safety.get(key) != 0 for key in required_zero):
        raise ValueError("replica successor safety boundary is incomplete")
    return document


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
        raise ValueError("tracked worktree must be clean before successor apply")
    hashes = plan.get("input_hashes")
    if not isinstance(hashes, Mapping):
        raise ValueError("replica successor input hashes are missing")
    for relative, expected in hashes.items():
        candidate = (PROJECT_ROOT / str(relative)).resolve(strict=True)
        candidate.relative_to(PROJECT_ROOT)
        if sha256_bytes(candidate.read_bytes()) != expected:
            raise ValueError(f"replica successor input hash drift: {relative}")


def _docker(args: Sequence[str], *, input_bytes: bytes | None = None) -> bytes:
    completed = subprocess.run(
        [str(DOCKER), *args], cwd=PROJECT_ROOT, input=input_bytes,
        check=True, capture_output=True,
    )
    return completed.stdout


def _inspect_container() -> dict[str, Any]:
    payload = json.loads(_docker(["inspect", CONTAINER_NAME]))
    if not isinstance(payload, list) or len(payload) != 1:
        raise ValueError("replica successor container identity is ambiguous")
    return payload[0]


def _assert_partial_identity(plan: Mapping[str, Any]) -> bytes:
    if not DOCKER.is_file() or not SECRET_FILE.is_file():
        raise ValueError("replica successor Docker or credential precondition is absent")
    if (SECRET_FILE.stat().st_mode & 0o777) != 0o600:
        raise ValueError("replica credential permissions are not 0600")
    inspected = _inspect_container()
    partial = plan["partial_state"]
    if inspected.get("Id") != partial.get("container_id"):
        raise ValueError("replica successor container id differs from approval")
    if inspected.get("Config", {}).get("Image") != IMAGE:
        raise ValueError("replica successor image differs from approval")
    state = inspected.get("State", {})
    if state.get("Status") != "running" or state.get("Health", {}).get("Status") != "healthy":
        raise ValueError("replica successor container is not running and healthy")
    mounts = {item.get("Destination"): item.get("Name") for item in inspected.get("Mounts", [])}
    if mounts.get("/data") != VOLUME_NAME or mounts.get("/logs") != partial.get("log_volume_name"):
        raise ValueError("replica successor volume identity differs from approval")
    config = _docker(["exec", CONTAINER_NAME, "cat", CONFIG_PATH])
    if sha256(config).hexdigest() != partial.get("config_sha256"):
        raise ValueError("replica successor generated configuration hash differs from approval")
    if WRITABLE_LINE.strip() in {line.strip() for line in config.splitlines()}:
        raise ValueError("replica successor unexpectedly starts with a writable exception")
    return config


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
    _docker(["cp", "-a", "-", f"{CONTAINER_NAME}:/var/lib/neo4j/conf"], input_bytes=_tar_config(config))
    actual = _docker(["exec", CONTAINER_NAME, "cat", CONFIG_PATH])
    if actual != config:
        raise RuntimeError("replica successor configuration replacement did not verify")


def _restart_container() -> None:
    _docker(["restart", CONTAINER_NAME])


def _wait_for_database(password: str, *, expected_access: str, timeout_seconds: float = 180.0) -> None:
    system = _client(HTTP_PORT, "neo4j", password, database="system")
    deadline = time.monotonic() + timeout_seconds
    last: list[object] | None = None
    while time.monotonic() < deadline:
        try:
            rows = system.run(
                "SHOW DATABASES YIELD name, access, currentStatus "
                "WHERE name = 'neo4j' RETURN name, access, currentStatus"
            )
            last = rows[0]["row"] if rows else None
            if last == ["neo4j", expected_access, "online"]:
                return
        except Exception:
            pass
        time.sleep(2.0)
    raise TimeoutError(f"replica database did not reach {expected_access}/online; last={last!r}")


def _source_counts(source_env_file: Path) -> tuple[Any, dict[str, tuple[int, int]]]:
    values = read_env(source_env_file.resolve(strict=True))
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


def _assert_offline_read_only_partial_state(password: str) -> None:
    system = _client(HTTP_PORT, "neo4j", password, database="system")
    rows = system.run(
        "SHOW DATABASES YIELD name, access, requestedStatus, currentStatus "
        "WHERE name = 'neo4j' "
        "RETURN name, access, requestedStatus, currentStatus"
    )
    actual = rows[0]["row"] if len(rows) == 1 else None
    if actual != ["neo4j", "read-only", "online", "offline"]:
        raise ValueError("replica successor database partial state differs from approval")


def apply_plan(*, plan: Mapping[str, Any], source_env_file: Path, run_id: str) -> dict[str, object]:
    if RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise ValueError("replica successor run id has an unsafe format")
    _verify_commit_and_hashes(plan)
    original_config = _assert_partial_identity(plan)
    secret = read_env(SECRET_FILE)
    password = secret.get("RECPRO_READONLY_NEO4J_PASSWORD", "")
    if not password:
        raise ValueError("replica successor credential is incomplete")
    _assert_offline_read_only_partial_state(password)
    source, source_before = _source_counts(source_env_file)
    if source_before != SOURCE_BASELINE:
        raise ValueError("source graph differs from the frozen successor baseline")

    target = _client(HTTP_PORT, "neo4j", password)
    imported: dict[str, dict[str, int]] = {}
    restored = False
    try:
        writable_config = original_config + (b"" if original_config.endswith(b"\n") else b"\n") + WRITABLE_LINE
        _replace_config(writable_config)
        _restart_container()
        _wait_for_database(password, expected_access="read-write")
        empty = {
            "v1": cypher_count_graph_version(target, "lib-books-v1-20260810"),
            "v2": cypher_count_graph_version(target, "lib-books-v2-20260828"),
        }
        if empty != {"v1": (0, 0), "v2": (0, 0)}:
            raise ValueError("replica successor expected an empty graph partial state")
        imported["v1"] = _append_graph(target, V1_DIR)
        imported["v2"] = _append_graph(target, V2_DIR)
    finally:
        _replace_config(original_config)
        _restart_container()
        _wait_for_database(password, expected_access="read-only")
        restored = True

    if not restored:
        raise RuntimeError("replica successor failed to restore read-only configuration")
    if sha256(_docker(["exec", CONTAINER_NAME, "cat", CONFIG_PATH])).hexdigest() != plan["partial_state"]["config_sha256"]:
        raise RuntimeError("replica successor original configuration was not restored")
    settings = _read_access_settings(target)
    expected_settings = {
        "server.databases.default_to_read_only": "true",
        "server.databases.writable": "",
    }
    if settings != expected_settings:
        raise RuntimeError("replica successor did not finish in read-only mode")
    replica_counts = {
        "v1": cypher_count_graph_version(target, "lib-books-v1-20260810"),
        "v2": cypher_count_graph_version(target, "lib-books-v2-20260828"),
    }
    source_after = {
        "v1": cypher_count_graph_version(source, "lib-books-v1-20260810"),
        "v2": cypher_count_graph_version(source, "lib-books-v2-20260828"),
    }
    if replica_counts != SOURCE_BASELINE or source_after != source_before:
        raise RuntimeError("replica successor reconciliation failed")
    report: dict[str, object] = {
        "schema_version": "neo4j-readonly-replica-successor-acceptance-v1",
        "status": "PASS",
        "run_id": run_id,
        "plan_id": plan["plan_id"],
        "plan_hash": plan["plan_hash"],
        "imported": imported,
        "replica_counts": replica_counts,
        "source_before": source_before,
        "source_after": source_after,
        "access_settings": settings,
        "config_restored_sha256": plan["partial_state"]["config_sha256"],
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
    parser.add_argument("--run-id", default="neo4j-readonly-replica-successor-20260829-001")
    args = parser.parse_args(argv)
    if not args.apply:
        print(json.dumps(dry_run_report(), ensure_ascii=False, indent=2))
        return 0
    if not args.plan or not args.plan_id or not args.approved_plan_hash:
        raise ValueError("successor apply requires exact plan path, id, and hash")
    plan = _load_plan(args.plan, plan_id=args.plan_id, plan_hash=args.approved_plan_hash)
    print(json.dumps(apply_plan(
        plan=plan, source_env_file=args.source_env_file, run_id=args.run_id,
    ), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
