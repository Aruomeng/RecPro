#!/usr/bin/env python3
"""Preflight and run the real local LibraMAS research workbench."""

from __future__ import annotations

import argparse
from http.client import HTTPConnection
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
TRUE_FLAGS = (
    "RECPRO_G4_HTTP_ENABLED",
    "RECPRO_G5_INTERACTION_HTTP_ENABLED",
    "RECPRO_G4_LLM_INTENT_ENABLED",
    "RECPRO_G4_LLM_EXPLANATION_ENABLED",
)


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
    chroma_path = PROJECT_ROOT / values.get("RECPRO_G4_CHROMA_PATH", "data/chroma")
    chroma_packages = PROJECT_ROOT / values.get(
        "RECPRO_G4_CHROMA_SITE_PACKAGES",
        ".venv-chroma-g6-20260811/lib/python3.11/site-packages",
    )
    if not chroma_path.is_dir() or not chroma_packages.is_dir():
        raise RuntimeError("versioned Chroma data or its isolated runtime is unavailable")
    if not (PROJECT_ROOT / "frontend" / "node_modules").is_dir():
        raise RuntimeError("frontend dependencies are unavailable; run npm ci in frontend")
    if shutil.which("npm") is None:
        raise RuntimeError("npm is unavailable")
    return {
        "status": "READY",
        "backend_url": f"http://127.0.0.1:{backend_port}",
        "frontend_url": f"http://127.0.0.1:{frontend_port}",
        "mysql": f"{mysql_host}:{mysql_port}",
        "neo4j": f"127.0.0.1:{graph_port}",
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
        connection = HTTPConnection(target.hostname, target.port, timeout=2)
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
    values = {**host_values, **secret_values}
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
            args.npm,
            "--prefix",
            "frontend",
            "run",
            "dev",
            "--",
            "--port",
            str(args.frontend_port),
        ],
        cwd=PROJECT_ROOT,
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
    parser.add_argument("--backend-port", type=int, default=8000)
    parser.add_argument("--frontend-port", type=int, default=5173)
    parser.add_argument("--startup-timeout", type=float, default=90.0)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--npm", default="npm")
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
