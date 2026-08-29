#!/usr/bin/env python3
"""Preflight and run the real local LibraMAS research workbench."""

from __future__ import annotations

import argparse
import base64
from http.client import HTTPConnection
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
from typing import Mapping, Sequence
from urllib.parse import urlsplit

from scripts.validate_runtime_env import read_env


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUNDLED_NODE = (
    Path.home()
    / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
)
TRUE_FLAGS = (
    "RECPRO_G4_HTTP_ENABLED",
    "RECPRO_G5_INTERACTION_HTTP_ENABLED",
    "RECPRO_G4_LLM_INTENT_ENABLED",
    "RECPRO_G4_LLM_EXPLANATION_ENABLED",
)
FINAL_GRAPH_KEYS = (
    "RECPRO_FINAL_NEO4J_PROJECT_NAME",
    "RECPRO_FINAL_NEO4J_HTTP_HOST_PORT",
    "RECPRO_FINAL_NEO4J_BOLT_HOST_PORT",
    "RECPRO_FINAL_NEO4J_PASSWORD",
)
EXPECTED_GRAPH_COUNTS = {
    "lib-books-v1-20260810": (63388, 191865),
    "lib-books-v2-20260828": (78129, 206848),
}
FINAL_GRAPH_ACCEPTANCE = (
    PROJECT_ROOT
    / "artifacts/verification/neo4j-readonly-replica"
    / "neo4j-readonly-final-20260829-001/acceptance.json"
)


def merge_runtime_values(
    host_values: Mapping[str, str],
    secret_values: Mapping[str, str],
    graph_values: Mapping[str, str],
) -> dict[str, str]:
    missing = [name for name in FINAL_GRAPH_KEYS if not graph_values.get(name, "").strip()]
    if missing:
        raise RuntimeError(f"final read-only graph secrets are incomplete: {','.join(missing)}")
    values = {**host_values, **secret_values}
    values.update({
        "RECPRO_LIBRARY_NEO4J_PROJECT_NAME": graph_values["RECPRO_FINAL_NEO4J_PROJECT_NAME"],
        "RECPRO_LIBRARY_NEO4J_HTTP_HOST_PORT": graph_values["RECPRO_FINAL_NEO4J_HTTP_HOST_PORT"],
        "RECPRO_LIBRARY_NEO4J_BOLT_HOST_PORT": graph_values["RECPRO_FINAL_NEO4J_BOLT_HOST_PORT"],
        "RECPRO_NEO4J_READ_USER": "neo4j",
        "RECPRO_NEO4J_READ_PASSWORD": graph_values["RECPRO_FINAL_NEO4J_PASSWORD"],
    })
    return values


def validate_configuration(values: Mapping[str, str]) -> tuple[str, ...]:
    issues: list[str] = []
    if values.get("RECPRO_APP_ENV", "").lower() != "demo":
        issues.append("RECPRO_APP_ENV must be demo")
    for name in TRUE_FLAGS:
        if values.get(name, "").lower() != "true":
            issues.append(f"{name} must be true")
    if values.get("RECPRO_LLM_PROVIDER") != "deepseek":
        issues.append("RECPRO_LLM_PROVIDER must be deepseek")
    if values.get("RECPRO_LLM_MODEL") != "deepseek-v4-flash":
        issues.append("RECPRO_LLM_MODEL must be deepseek-v4-flash")
    for name in (
        "RECPRO_LLM_API_KEY",
        "RECPRO_MYSQL_HOST",
        "RECPRO_MYSQL_PORT",
        "RECPRO_LIBRARY_NEO4J_HTTP_HOST_PORT",
        "RECPRO_NEO4J_READ_USER",
        "RECPRO_NEO4J_READ_PASSWORD",
    ):
        if not values.get(name, "").strip():
            issues.append(f"{name} must be configured")
    return tuple(issues)


def require_free_port(port: int, *, label: str) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError as exc:
            raise RuntimeError(f"{label} port {port} is already in use") from exc


def require_tcp(host: str, port: int, *, label: str) -> None:
    try:
        with socket.create_connection((host, port), timeout=3):
            pass
    except OSError as exc:
        raise RuntimeError(f"{label} is unavailable at {host}:{port}") from exc


def require_http(url: str, *, label: str) -> None:
    target = urlsplit(url)
    connection = HTTPConnection(target.hostname, target.port, timeout=5)
    try:
        connection.request("GET", target.path or "/")
        response = connection.getresponse()
        if response.status >= 500:
            raise RuntimeError(f"{label} returned HTTP {response.status}")
    except OSError as exc:
        raise RuntimeError(f"{label} is unavailable at {url}") from exc
    finally:
        connection.close()


def neo4j_rows(
    *, port: int, database: str, username: str, password: str,
    statement: str, parameters: Mapping[str, object] | None = None,
) -> list[list[object]]:
    authorization = base64.b64encode(f"{username}:{password}".encode()).decode()
    connection = HTTPConnection("127.0.0.1", port, timeout=15)
    try:
        connection.request(
            "POST",
            f"/db/{database}/tx/commit",
            body=json.dumps({"statements": [{
                "statement": statement,
                "parameters": dict(parameters or {}),
                "resultDataContents": ["row"],
            }]}).encode(),
            headers={
                "Authorization": f"Basic {authorization}",
                "Content-Type": "application/json",
            },
        )
        response = connection.getresponse()
        payload = json.loads(response.read().decode())
    finally:
        connection.close()
    if response.status >= 400 or payload.get("errors"):
        raise RuntimeError("final Neo4j rejected the read-only preflight query")
    results = payload.get("results", [])
    if len(results) != 1:
        raise RuntimeError("final Neo4j returned an invalid preflight result")
    return [item.get("row", []) for item in results[0].get("data", [])]


def require_final_readonly_graph(values: Mapping[str, str]) -> dict[str, object]:
    port = int(values["RECPRO_LIBRARY_NEO4J_HTTP_HOST_PORT"])
    username = values["RECPRO_NEO4J_READ_USER"]
    password = values["RECPRO_NEO4J_READ_PASSWORD"]
    state = neo4j_rows(
        port=port, database="system", username=username, password=password,
        statement=(
            "SHOW DATABASES YIELD name, access, currentStatus "
            "WHERE name = 'neo4j' RETURN name, access, currentStatus"
        ),
    )
    if state != [["neo4j", "read-only", "online"]]:
        raise RuntimeError("final Neo4j is not online/read-only")
    acceptance = json.loads(FINAL_GRAPH_ACCEPTANCE.resolve(strict=True).read_text(encoding="utf-8"))
    if acceptance.get("status") != "PASS":
        raise RuntimeError("final Neo4j acceptance evidence is not PASS")
    accepted_counts = acceptance.get("replica_counts")
    expected_evidence = {
        "v1": [*EXPECTED_GRAPH_COUNTS["lib-books-v1-20260810"]],
        "v2": [*EXPECTED_GRAPH_COUNTS["lib-books-v2-20260828"]],
    }
    if accepted_counts != expected_evidence:
        raise RuntimeError("final Neo4j acceptance evidence counts differ")
    node_rows = neo4j_rows(
        port=port, database="neo4j", username=username, password=password,
        statement="MATCH (n) RETURN count(n)",
    )
    relationship_rows = neo4j_rows(
        port=port, database="neo4j", username=username, password=password,
        statement="MATCH ()-[r]->() RETURN count(r)",
    )
    expected_totals = [
        sum(value[0] for value in EXPECTED_GRAPH_COUNTS.values()),
        sum(value[1] for value in EXPECTED_GRAPH_COUNTS.values()),
    ]
    if node_rows != [[expected_totals[0]]] or relationship_rows != [[expected_totals[1]]]:
        raise RuntimeError("final Neo4j live total counts differ from acceptance")
    return {
        "access": "read-only",
        "status": "online",
        "counts": {
            version: {"nodes": value[0], "relationships": value[1]}
            for version, value in EXPECTED_GRAPH_COUNTS.items()
        },
        "live_totals": {"nodes": expected_totals[0], "relationships": expected_totals[1]},
    }


def preflight(
    values: Mapping[str, str], *, backend_port: int, frontend_port: int
) -> dict[str, object]:
    issues = validate_configuration(values)
    if issues:
        raise RuntimeError("; ".join(issues))
    require_free_port(backend_port, label="research backend")
    require_free_port(frontend_port, label="research frontend")
    mysql_host = values.get("RECPRO_MYSQL_HOST", "127.0.0.1")
    mysql_port = int(values["RECPRO_MYSQL_PORT"])
    graph_port = int(values["RECPRO_LIBRARY_NEO4J_HTTP_HOST_PORT"])
    require_tcp(mysql_host, mysql_port, label="isolated MySQL")
    require_http(f"http://127.0.0.1:{graph_port}/", label="isolated library Neo4j")
    graph_acceptance = require_final_readonly_graph(values)
    chroma_path = PROJECT_ROOT / values.get("RECPRO_G4_CHROMA_PATH", "data/chroma")
    chroma_packages = PROJECT_ROOT / values.get(
        "RECPRO_G4_CHROMA_SITE_PACKAGES",
        ".venv-chroma-g6-20260811/lib/python3.11/site-packages",
    )
    if not chroma_path.is_dir() or not chroma_packages.is_dir():
        raise RuntimeError("versioned Chroma data or its isolated runtime is unavailable")
    if not (PROJECT_ROOT / "frontend" / "node_modules").is_dir():
        raise RuntimeError("frontend dependencies are unavailable; run npm ci in frontend")
    return {
        "status": "READY",
        "backend_url": f"http://127.0.0.1:{backend_port}",
        "frontend_url": f"http://127.0.0.1:{frontend_port}",
        "mysql": f"{mysql_host}:{mysql_port}",
        "neo4j": f"127.0.0.1:{graph_port}",
        "neo4j_access": graph_acceptance["access"],
        "neo4j_status": graph_acceptance["status"],
        "neo4j_counts": graph_acceptance["counts"],
        "neo4j_live_totals": graph_acceptance["live_totals"],
        "llm_provider": "deepseek",
        "llm_model": "deepseek-v4-flash",
        "g4_enabled": True,
        "g5_enabled": True,
        "files_deleted": 0,
        "database_writes": 0,
    }


def wait_for_url(url: str, *, timeout: float) -> None:
    target = urlsplit(url)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = max(0.1, deadline - time.monotonic())
        connection = HTTPConnection(
            target.hostname,
            target.port,
            timeout=min(20.0, remaining),
        )
        try:
            connection.request("GET", target.path or "/")
            response = connection.getresponse()
            if response.status < 500:
                return
        except OSError:
            time.sleep(0.5)
        finally:
            connection.close()
    raise RuntimeError(f"startup timed out waiting for {url}")


def stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def run(args: argparse.Namespace) -> int:
    host_values = read_env(args.env_file.resolve(strict=True))
    secret_values = read_env(args.secrets_file.resolve(strict=True))
    graph_values = read_env(args.graph_secrets_file.resolve(strict=True))
    values = merge_runtime_values(host_values, secret_values, graph_values)
    node = args.node.expanduser()
    if not node.is_file() or not os.access(node, os.X_OK):
        raise RuntimeError(f"stable Node.js executable is unavailable: {node}")
    vite = PROJECT_ROOT / "frontend/node_modules/vite/bin/vite.js"
    if not vite.is_file():
        raise RuntimeError("Vite runtime entrypoint is unavailable")
    report = preflight(
        values, backend_port=args.backend_port, frontend_port=args.frontend_port
    )
    for key, value in report.items():
        print(f"{key}={value}")
    if args.check_only:
        return 0

    environment = {**os.environ, **values, "PYTHONDONTWRITEBYTECODE": "1"}
    backend = subprocess.Popen(
        [
            args.python,
            "-m",
            "uvicorn",
            "backend.app.g4_feedback_demo_main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(args.backend_port),
        ],
        cwd=PROJECT_ROOT,
        env=environment,
    )
    frontend = subprocess.Popen(
        [
            str(node),
            str(vite),
            "--host",
            "127.0.0.1",
            "--port",
            str(args.frontend_port),
        ],
        cwd=PROJECT_ROOT / "frontend",
        env=environment,
    )
    processes = (backend, frontend)
    shutdown_requested = False

    def handle_signal(_signum: int, _frame: object) -> None:
        nonlocal shutdown_requested
        shutdown_requested = True
        for process in processes:
            stop_process(process)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    try:
        wait_for_url(
            f"http://127.0.0.1:{args.backend_port}/api/v1/health/ready",
            timeout=args.startup_timeout,
        )
        wait_for_url(
            f"http://127.0.0.1:{args.frontend_port}/",
            timeout=args.startup_timeout,
        )
        print(f"LibraMAS workbench ready: http://127.0.0.1:{args.frontend_port}")
        while all(process.poll() is None for process in processes):
            time.sleep(0.5)
        if shutdown_requested:
            return 0
        return next(
            (process.returncode or 1 for process in processes if process.poll() is not None),
            1,
        )
    finally:
        for process in processes:
            stop_process(process)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.host")
    parser.add_argument(
        "--secrets-file", type=Path, default=PROJECT_ROOT / ".env.user-secrets"
    )
    parser.add_argument(
        "--graph-secrets-file",
        type=Path,
        default=PROJECT_ROOT / ".env.neo4j-readonly-final.local",
    )
    parser.add_argument("--backend-port", type=int, default=8000)
    parser.add_argument("--frontend-port", type=int, default=5173)
    parser.add_argument("--startup-timeout", type=float, default=90.0)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument(
        "--node",
        type=Path,
        default=BUNDLED_NODE if BUNDLED_NODE.is_file() else Path(shutil.which("node") or "node"),
    )
    parser.add_argument("--check-only", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"[FAIL] research workbench: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
