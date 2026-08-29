#!/usr/bin/env python3
"""Apply the exact additive Neo4j read-only replica ChangePlan.

Dry-run is the default and performs no Docker, database, secret, or network
operation. Apply is fail-forward: it never removes a file, container, volume,
constraint, node, or relationship. If import fails after temporary write access
is enabled, the finally block removes that exception before reporting failure.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import time
from typing import Any, Mapping, Sequence
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener

from scripts.build_neo4j_readonly_replica_plan import (
    BOLT_PORT,
    COMPOSE_FILE,
    HTTP_PORT,
    PROJECT_NAME,
    PROJECT_ROOT,
    V1_DIR,
    V2_DIR,
    VOLUME_NAME,
)
from scripts.import_book_graph import (
    Neo4jHttpClient,
    canonical_json,
    create_constraints,
    cypher_count_graph_version,
    import_nodes,
    import_triples,
    sha256_bytes,
    verify_plan,
)
from scripts.validate_runtime_env import read_env


DOCKER = Path("/Applications/编程/Docker.app/Contents/Resources/bin/docker")
SECRET_FILE = PROJECT_ROOT / ".env.neo4j-readonly.local"
EVIDENCE_ROOT = PROJECT_ROOT / "artifacts/verification/neo4j-readonly-replica"
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")


def _canonical_hash(document: Mapping[str, Any]) -> str:
    from hashlib import sha256

    payload = dict(document)
    payload.pop("plan_hash", None)
    return sha256(canonical_json(payload).encode()).hexdigest()


def _load_plan(path: Path, *, plan_id: str, plan_hash: str) -> dict[str, Any]:
    resolved = path.resolve(strict=True)
    try:
        resolved.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError("replica plan must be inside the repository") from exc
    document = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("replica plan must be a JSON object")
    if document.get("plan_id") != plan_id or document.get("plan_hash") != plan_hash:
        raise ValueError("approved replica plan identity does not match")
    if _canonical_hash(document) != plan_hash:
        raise ValueError("replica plan canonical hash does not match")
    if document.get("schema_version") != "recpro-neo4j-readonly-replica-plan-v1":
        raise ValueError("unsupported replica plan schema")
    safety = document.get("safety")
    required_zero = (
        "file_deletions",
        "database_deletions",
        "container_deletions",
        "volume_deletions",
        "existing_container_changes",
        "existing_volume_changes",
        "source_graph_writes",
        "deepseek_requests",
    )
    if not isinstance(safety, Mapping) or any(safety.get(key) != 0 for key in required_zero):
        raise ValueError("replica plan safety boundary is incomplete")
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
        raise ValueError("tracked worktree must be clean before replica apply")
    hashes = plan.get("input_hashes")
    if not isinstance(hashes, Mapping):
        raise ValueError("replica plan input hashes are missing")
    for relative, expected in hashes.items():
        path = (PROJECT_ROOT / str(relative)).resolve(strict=True)
        path.relative_to(PROJECT_ROOT)
        if sha256_bytes(path.read_bytes()) != expected:
            raise ValueError(f"replica input hash drift: {relative}")


def _run(command: Sequence[str], *, env: Mapping[str, str] | None = None) -> str:
    return subprocess.run(
        list(command), cwd=PROJECT_ROOT, check=True, capture_output=True,
        text=True, env=dict(env) if env is not None else None,
    ).stdout.strip()


def _docker_absence_guard() -> None:
    if not DOCKER.is_file():
        raise ValueError("approved Docker executable is unavailable")
    containers = _run([
        str(DOCKER), "ps", "-a", "--quiet", "--filter",
        f"label=com.docker.compose.project={PROJECT_NAME}",
    ])
    if containers:
        raise ValueError("replica Compose project already exists")
    volume = subprocess.run(
        [str(DOCKER), "volume", "inspect", VOLUME_NAME],
        cwd=PROJECT_ROOT, capture_output=True, text=True,
    )
    if volume.returncode == 0:
        raise ValueError("replica volume already exists")
    if SECRET_FILE.exists():
        raise ValueError("replica credential file already exists")


def _write_secret_file(password: str) -> None:
    lines = (
        f"RECPRO_READONLY_NEO4J_PROJECT_NAME={PROJECT_NAME}\n"
        f"RECPRO_READONLY_NEO4J_VOLUME_NAME={VOLUME_NAME}\n"
        f"RECPRO_READONLY_NEO4J_HTTP_HOST_PORT={HTTP_PORT}\n"
        f"RECPRO_READONLY_NEO4J_BOLT_HOST_PORT={BOLT_PORT}\n"
        f"RECPRO_READONLY_NEO4J_PASSWORD={password}\n"
    )
    descriptor = os.open(SECRET_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(lines)


def _wait_for_http(password: str, *, timeout_seconds: float = 180.0) -> None:
    import base64

    authorization = base64.b64encode(f"neo4j:{password}".encode()).decode()
    request = Request(
        f"http://127.0.0.1:{HTTP_PORT}/db/neo4j/tx/commit",
        data=b'{"statements":[{"statement":"RETURN 1"}]}',
        headers={
            "Authorization": f"Basic {authorization}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    opener = build_opener(ProxyHandler({}))
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with opener.open(request, timeout=3.0) as response:
                payload = json.loads(response.read().decode())
            if not payload.get("errors"):
                return
        except (OSError, URLError, TimeoutError, json.JSONDecodeError):
            pass
        time.sleep(2.0)
    raise TimeoutError("replica Neo4j did not become ready within the bounded wait")


def _client(port: int, username: str, password: str, *, database: str = "neo4j") -> Neo4jHttpClient:
    return Neo4jHttpClient(
        endpoint=f"http://127.0.0.1:{port}/db/{database}/tx/commit",
        username=username, password=password, timeout=15.0,
    )


def _set_writable_exception(client: Neo4jHttpClient, value: str) -> None:
    client.run(
        "CALL dbms.setConfigValue('server.databases.writable', $value)",
        {"value": value}, write=True,
    )


def _read_access_settings(client: Neo4jHttpClient) -> dict[str, str]:
    rows = client.run(
        "CALL dbms.listConfig() YIELD name, value "
        "WHERE name IN ['server.databases.default_to_read_only', 'server.databases.writable'] "
        "RETURN name, value ORDER BY name"
    )
    return {str(row["row"][0]): str(row["row"][1]) for row in rows}


def _append_graph(client: Neo4jHttpClient, plan_dir: Path, *, batch_size: int = 1000) -> dict[str, int]:
    plan, nodes, triples = verify_plan(plan_dir)
    node_labels = {str(node["graph_key"]): str(node["label"]) for node in nodes}
    create_constraints(client)
    return {
        "nodes": import_nodes(client, nodes, batch_size=batch_size),
        "relationships": import_triples(
            client, triples, node_labels,
            graph_version=str(plan["graph_version"]), batch_size=batch_size,
        ),
    }


def dry_run_report() -> dict[str, object]:
    v1_plan, v1_nodes, v1_triples = verify_plan(V1_DIR)
    v2_plan, v2_nodes, v2_triples = verify_plan(V2_DIR)
    return {
        "mode": "DRY_RUN",
        "v1": {"version": v1_plan["graph_version"], "nodes": len(v1_nodes), "relationships": len(v1_triples)},
        "v2": {"version": v2_plan["graph_version"], "nodes": len(v2_nodes), "relationships": len(v2_triples)},
        "new_containers": 1,
        "new_volumes": 1,
        "new_secret_files": 1,
        "existing_graph_writes": 0,
        "database_deletions": 0,
        "container_deletions": 0,
        "volume_deletions": 0,
        "deepseek_requests": 0,
        "docker_connections": 0,
        "database_connections": 0,
    }


def apply_plan(
    *, plan: Mapping[str, Any], source_env_file: Path, run_id: str,
) -> dict[str, object]:
    if RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise ValueError("replica run id has an unsafe format")
    _verify_commit_and_hashes(plan)
    _docker_absence_guard()
    source_env_path = source_env_file.resolve(strict=True)
    try:
        source_env_path.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError("source environment file must be inside the repository") from exc
    source_values = read_env(source_env_path)
    required = (
        "RECPRO_LIBRARY_NEO4J_HTTP_HOST_PORT",
        "RECPRO_NEO4J_ADMIN_USER",
        "RECPRO_NEO4J_ADMIN_PASSWORD",
    )
    if any(not source_values.get(key) for key in required):
        raise ValueError("source Neo4j environment is incomplete")
    source_client = _client(
        int(source_values["RECPRO_LIBRARY_NEO4J_HTTP_HOST_PORT"]),
        source_values["RECPRO_NEO4J_ADMIN_USER"],
        source_values["RECPRO_NEO4J_ADMIN_PASSWORD"],
    )
    before = {
        "v1": cypher_count_graph_version(source_client, "lib-books-v1-20260810"),
        "v2": cypher_count_graph_version(source_client, "lib-books-v2-20260828"),
    }
    if before != {"v1": (63388, 191865), "v2": (78129, 206848)}:
        raise ValueError("source graph counts differ from the frozen replica baseline")

    password = secrets.token_urlsafe(36)
    _write_secret_file(password)
    compose_env = os.environ.copy()
    compose_env.update(read_env(SECRET_FILE))
    _run([
        str(DOCKER), "compose", "-f", str(COMPOSE_FILE),
        "--env-file", str(SECRET_FILE), "up", "-d", "neo4j-readonly",
    ], env=compose_env)
    _wait_for_http(password)
    target = _client(HTTP_PORT, "neo4j", password)
    system = _client(HTTP_PORT, "neo4j", password, database="system")
    writable_enabled = False
    imported: dict[str, dict[str, int]] = {}
    try:
        _set_writable_exception(system, "neo4j")
        writable_enabled = True
        imported["v1"] = _append_graph(target, V1_DIR)
        imported["v2"] = _append_graph(target, V2_DIR)
    finally:
        if writable_enabled:
            try:
                _set_writable_exception(system, "")
            except Exception:
                # Dynamic settings do not survive restart. The immutable
                # Compose default is read-only, so a bounded restart is the
                # fail-safe if the system-database reset cannot be confirmed.
                _run([
                    str(DOCKER), "compose", "-f", str(COMPOSE_FILE),
                    "--env-file", str(SECRET_FILE), "restart", "neo4j-readonly",
                ], env=compose_env)
                _wait_for_http(password)
                raise RuntimeError(
                    "writable exception reset failed; replica restarted read-only"
                )

    settings = _read_access_settings(target)
    if settings != {
        "server.databases.default_to_read_only": "true",
        "server.databases.writable": "",
    }:
        raise RuntimeError("replica did not finish in the required read-only mode")
    replica_counts = {
        "v1": cypher_count_graph_version(target, "lib-books-v1-20260810"),
        "v2": cypher_count_graph_version(target, "lib-books-v2-20260828"),
    }
    after = {
        "v1": cypher_count_graph_version(source_client, "lib-books-v1-20260810"),
        "v2": cypher_count_graph_version(source_client, "lib-books-v2-20260828"),
    }
    if replica_counts != before or after != before:
        raise RuntimeError("replica or immutable source counts failed reconciliation")

    report: dict[str, object] = {
        "schema_version": "neo4j-readonly-replica-acceptance-v1",
        "status": "PASS",
        "run_id": run_id,
        "plan_id": plan["plan_id"],
        "plan_hash": plan["plan_hash"],
        "replica": plan["replica"],
        "imported": imported,
        "replica_counts": {key: {"nodes": value[0], "relationships": value[1]} for key, value in replica_counts.items()},
        "source_before": {key: {"nodes": value[0], "relationships": value[1]} for key, value in before.items()},
        "source_after": {key: {"nodes": value[0], "relationships": value[1]} for key, value in after.items()},
        "access_settings": settings,
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
    parser.add_argument("--run-id", default="neo4j-readonly-replica-20260829-001")
    args = parser.parse_args(argv)
    if not args.apply:
        print(json.dumps(dry_run_report(), ensure_ascii=False, indent=2))
        return 0
    if not args.plan or not args.plan_id or not args.approved_plan_hash:
        raise ValueError("apply requires exact plan path, plan id, and approved hash")
    plan = _load_plan(
        args.plan, plan_id=args.plan_id, plan_hash=args.approved_plan_hash,
    )
    report = apply_plan(
        plan=plan, source_env_file=args.source_env_file, run_id=args.run_id,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
