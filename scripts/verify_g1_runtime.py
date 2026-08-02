"""Run the non-destructive G1 Compose restart acceptance check.

The verifier uses HTTP GET, Docker status/inspect, four read-only SQL count
queries, service start, and service stop operations. It never removes containers,
volumes, files, or database data. Evidence is written to a new run directory and
an existing run is never reused.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Mapping, Sequence

from scripts.validate_runtime_env import read_env, validate_compose


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
GIT_COMMIT_PATTERN = re.compile(r"^[a-f0-9]{40}$")
EXPECTED_SERVICES = ("mysql", "neo4j", "backend", "worker", "frontend")
HEALTHY_SERVICES = frozenset({"mysql", "neo4j", "backend", "frontend"})
SENSITIVE_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(password|secret|token|api[_-]?key)\s*=\s*[^\s;]+"
)


@dataclass(frozen=True)
class CommandResult:
    stdout: str
    stderr: str


class _FrontendHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.has_app_root = False
        self.in_title = False
        self.title_parts: list[str] = []
        self.assets: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        attributes = dict(attrs)
        if tag == "div" and attributes.get("id") == "app":
            self.has_app_root = True
        if tag == "title":
            self.in_title = True
        if tag == "script" and attributes.get("src"):
            self.assets.append(str(attributes["src"]))
        if tag == "link" and attributes.get("href"):
            rel = (attributes.get("rel") or "").casefold().split()
            if "stylesheet" in rel:
                self.assets.append(str(attributes["href"]))

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)


def validate_run_id(value: str) -> str:
    if not RUN_ID_PATTERN.fullmatch(value):
        raise ValueError(
            "RUN_ID must be 3-64 characters using letters, numbers, dot, dash, or underscore"
        )
    return value


def run_command(command: Sequence[str], *, timeout: int = 180) -> CommandResult:
    completed = subprocess.run(
        list(command),
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if completed.returncode != 0:
        command_name = " ".join(command[:3])
        raise RuntimeError(
            f"command failed ({command_name}, exit={completed.returncode}); "
            "inspect the local Docker logs without publishing environment values"
        )
    return CommandResult(completed.stdout, completed.stderr)


def fetch_json(url: str, *, timeout: float = 3.0) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.status
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        status = exc.code
        body = exc.read().decode("utf-8")
    parsed = json.loads(body)
    if not isinstance(parsed, dict):
        raise ValueError(f"expected a JSON object from {url}")
    return status, parsed


def validate_health_pair(
    live_status: int,
    live: dict[str, Any],
    ready_status: int,
    ready: dict[str, Any],
    expected_probe_id: str | None = None,
) -> None:
    if live_status != 200 or live.get("status") != "UP":
        raise ValueError("liveness did not report HTTP 200 with status=UP")
    if ready_status != 200:
        raise ValueError("readiness did not report HTTP 200 in the isolated G1 environment")
    if ready.get("status") != "DEGRADED":
        raise ValueError("G1 readiness must truthfully report status=DEGRADED")
    if ready.get("can_recommend") is not False:
        raise ValueError("G1 must report can_recommend=false until the recommendation chain exists")
    components = ready.get("components")
    if not isinstance(components, dict) or components.get("mysql", {}).get("status") != "UP":
        raise ValueError("G1 readiness must report the isolated MySQL dependency as UP")
    if expected_probe_id is not None and components["mysql"].get("active_version") != expected_probe_id:
        raise ValueError("MySQL persistence probe identity does not match the isolated project")


def stable_health_signature(value: Mapping[str, Any]) -> dict[str, Any]:
    """Return a JSON-safe health value without observation timestamps."""

    signature = json.loads(json.dumps(value))
    signature.pop("time", None)
    signature.pop("checked_at", None)
    return signature


def fetch_text(url: str, *, timeout: float = 3.0) -> tuple[int, str]:
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status, response.read().decode("utf-8")


def fetch_bytes(url: str, *, timeout: float = 3.0) -> tuple[int, bytes, str]:
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return (
            response.status,
            response.read(),
            response.headers.get_content_type().casefold(),
        )


def parse_frontend_entrypoint(html: str) -> tuple[str, ...]:
    parser = _FrontendHTMLParser()
    parser.feed(html)
    title = "".join(parser.title_parts).strip()
    if title != "LibraMAS · 系统状态" or not parser.has_app_root:
        raise ValueError("frontend entrypoint is missing the stable title or app root")

    assets = tuple(dict.fromkeys(parser.assets))
    if not any(path.endswith(".js") for path in assets) or not any(
        path.endswith(".css") for path in assets
    ):
        raise ValueError("frontend entrypoint must reference production JS and CSS assets")
    for path in assets:
        parsed = urllib.parse.urlsplit(path)
        if (
            parsed.scheme
            or parsed.netloc
            or parsed.query
            or parsed.fragment
            or not parsed.path.startswith("/assets/")
            or ".." in Path(parsed.path).parts
        ):
            raise ValueError("frontend entrypoint contains an unsafe asset path")
    return assets


def inspect_frontend_page(frontend_base_url: str) -> dict[str, Any]:
    status, html = fetch_text(f"{frontend_base_url}/")
    if status != 200:
        raise ValueError("frontend entrypoint did not report HTTP 200")
    assets = parse_frontend_entrypoint(html)
    asset_evidence: list[dict[str, Any]] = []
    for path in assets:
        asset_status, body, content_type = fetch_bytes(f"{frontend_base_url}{path}")
        if asset_status != 200 or not body:
            raise ValueError("frontend production asset is missing or empty")
        expected_content_types = (
            {"application/javascript", "text/javascript"}
            if path.endswith(".js")
            else {"text/css"}
        )
        if content_type not in expected_content_types:
            raise ValueError("frontend production asset has an unsafe content type")
        asset_evidence.append(
            {
                "path": path,
                "status": asset_status,
                "content_type": content_type,
                "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
            }
        )
    return {
        "status": status,
        "title": "LibraMAS · 系统状态",
        "assets": asset_evidence,
    }


def inspect_service_state(
    compose: Sequence[str], service_name: str
) -> dict[str, Any]:
    container_result = run_command((*compose, "ps", "--quiet", service_name), timeout=30)
    container_ids = [line.strip() for line in container_result.stdout.splitlines() if line.strip()]
    if len(container_ids) != 1:
        raise ValueError(f"expected exactly one container for service {service_name}")
    state_result = run_command(
        (
            "docker",
            "inspect",
            "--format",
            "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}|{{.RestartCount}}",
            container_ids[0],
        ),
        timeout=30,
    )
    parts = state_result.stdout.strip().split("|")
    if len(parts) != 3:
        raise ValueError(f"unexpected Docker state for service {service_name}")
    try:
        restart_count = int(parts[2])
    except ValueError as exc:
        raise ValueError(f"invalid restart count for service {service_name}") from exc
    return {
        "status": parts[0],
        "health": parts[1] or None,
        "restart_count": restart_count,
    }


def collect_service_states(compose: Sequence[str]) -> dict[str, dict[str, Any]]:
    return {
        service_name: inspect_service_state(compose, service_name)
        for service_name in EXPECTED_SERVICES
    }


def validate_service_states(states: Mapping[str, Mapping[str, Any]]) -> None:
    if set(states) != set(EXPECTED_SERVICES):
        raise ValueError("runtime service inventory is incomplete or contains unknown services")
    for service_name in EXPECTED_SERVICES:
        state = states[service_name]
        if state.get("status") != "running":
            raise ValueError(f"service {service_name} is not running")
        if state.get("restart_count") != 0:
            raise ValueError(f"service {service_name} restarted unexpectedly")
        if service_name in HEALTHY_SERVICES and state.get("health") != "healthy":
            raise ValueError(f"service {service_name} is not healthy")


def wait_for_runtime(
    *,
    compose: Sequence[str],
    backend_base_url: str,
    frontend_base_url: str,
    expected_probe_id: str,
    deadline_seconds: int,
) -> dict[str, Any]:
    deadline = time.monotonic() + deadline_seconds
    last_error = "service not contacted"
    while time.monotonic() < deadline:
        try:
            states = collect_service_states(compose)
            validate_service_states(states)

            live_status, live = fetch_json(f"{backend_base_url}/api/v1/health/live")
            ready_status, ready = fetch_json(f"{backend_base_url}/api/v1/health/ready")
            validate_health_pair(
                live_status,
                live,
                ready_status,
                ready,
                expected_probe_id,
            )

            proxy_live_status, proxy_live = fetch_json(
                f"{frontend_base_url}/api/v1/health/live"
            )
            proxy_ready_status, proxy_ready = fetch_json(
                f"{frontend_base_url}/api/v1/health/ready"
            )
            validate_health_pair(
                proxy_live_status,
                proxy_live,
                proxy_ready_status,
                proxy_ready,
                expected_probe_id,
            )
            if stable_health_signature(live) != stable_health_signature(proxy_live):
                raise ValueError("frontend proxy liveness differs from the backend")
            if stable_health_signature(ready) != stable_health_signature(proxy_ready):
                raise ValueError("frontend proxy readiness differs from the backend")

            frontend_status, frontend_body = fetch_text(f"{frontend_base_url}/healthz")
            if frontend_status != 200 or frontend_body.strip() != "ok":
                raise ValueError("frontend health endpoint did not report HTTP 200 ok")
            frontend_page = inspect_frontend_page(frontend_base_url)
            return {
                "direct": {"live": live, "ready": ready},
                "proxy": {"live": proxy_live, "ready": proxy_ready},
                "frontend_healthz": {"status": frontend_status, "body": "ok"},
                "frontend_page": frontend_page,
                "services": states,
            }
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
            last_error = str(exc)
            time.sleep(2)
    raise TimeoutError(f"G1 runtime deadline elapsed: {last_error}")


def inspect_volume(volume_name: str) -> dict[str, Any]:
    result = run_command(("docker", "volume", "inspect", volume_name), timeout=30)
    parsed = json.loads(result.stdout)
    if not isinstance(parsed, list) or len(parsed) != 1 or not isinstance(parsed[0], dict):
        raise ValueError("Docker returned an unexpected volume inspection response")
    item = parsed[0]
    return {"Name": item.get("Name"), "CreatedAt": item.get("CreatedAt")}


def parse_probe_counts(stdout: str) -> dict[str, int]:
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    if len(lines) != 2:
        raise ValueError("persistence probe count query returned an unexpected shape")
    try:
        total_rows, matching_probe_rows = (int(line) for line in lines)
    except ValueError as exc:
        raise ValueError("persistence probe count query returned a non-integer") from exc
    if total_rows != 1 or matching_probe_rows != 1:
        raise ValueError(
            "the isolated persistence probe must contain exactly one row for this project"
        )
    return {
        "total_rows": total_rows,
        "matching_probe_rows": matching_probe_rows,
    }


def query_probe_counts(compose: Sequence[str]) -> dict[str, int]:
    """Read the isolated marker table without displaying or passing secrets."""

    shell_program = (
        'exec mysql --protocol=socket '
        '--user="$RECPRO_MYSQL_RUNTIME_USER" '
        '--password="$RECPRO_MYSQL_RUNTIME_PASSWORD" '
        '--database="$MYSQL_DATABASE" '
        '--batch --skip-column-names '
        '--execute="SELECT COUNT(*) FROM recpro_runtime_probe; '
        "SELECT COUNT(*) FROM recpro_runtime_probe WHERE probe_id = "
        "'$RECPRO_PERSISTENCE_PROBE_ID';\""
    )
    result = run_command(
        (*compose, "exec", "--no-tty", "mysql", "sh", "-ceu", shell_program),
        timeout=30,
    )
    return parse_probe_counts(result.stdout)


def ensure_new_isolated_runtime(
    *,
    compose: Sequence[str],
    volume_names: Sequence[str],
    network_names: Sequence[str],
) -> None:
    existing_containers = run_command((*compose, "ps", "--all", "--quiet"), timeout=30)
    if existing_containers.stdout.strip():
        raise ValueError("the isolated Compose project already has containers")

    existing_volumes = set(
        run_command(("docker", "volume", "ls", "--format", "{{.Name}}"), timeout=30)
        .stdout.splitlines()
    )
    collisions = sorted(set(volume_names).intersection(existing_volumes))
    if collisions:
        raise ValueError(
            "the isolated Compose project would reuse existing named volumes: "
            + ", ".join(collisions)
        )

    existing_networks = set(
        run_command(("docker", "network", "ls", "--format", "{{.Name}}"), timeout=30)
        .stdout.splitlines()
    )
    network_collisions = sorted(set(network_names).intersection(existing_networks))
    if network_collisions:
        raise ValueError(
            "the isolated Compose project would reuse existing networks: "
            + ", ".join(network_collisions)
        )


def write_json_exclusive(path: Path, value: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def write_text_exclusive(path: Path, value: str) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(value)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validated_port(values: Mapping[str, str], key: str) -> int:
    try:
        value = int(values[key])
    except (KeyError, ValueError) as exc:
        raise ValueError(f"{key} must identify an explicit host port") from exc
    if not 1 <= value <= 65535:
        raise ValueError(f"{key} must be between 1 and 65535")
    return value


def validate_git_evidence_state(status_output: str, commit_output: str) -> str:
    if status_output.strip():
        raise ValueError(
            "runtime evidence requires a clean Git worktree so results match one commit"
        )
    commit = commit_output.strip()
    if not GIT_COMMIT_PATTERN.fullmatch(commit):
        raise ValueError("runtime evidence requires a full lowercase Git commit hash")
    return commit


def sanitized_failure_reason(error: Exception) -> str:
    reason = " ".join(str(error).split()) or type(error).__name__
    reason = reason.replace(str(PROJECT_ROOT), "<repository>")
    reason = SENSITIVE_ASSIGNMENT_PATTERN.sub(
        lambda match: f"{match.group(1)}=<redacted>",
        reason,
    )
    reason = re.sub(r"(://[^:/\s]+:)[^@\s]+@", r"\1<redacted>@", reason)
    return reason[:500]


def resolve_clean_git_commit() -> str:
    status = run_command(
        ("git", "status", "--porcelain", "--untracked-files=normal"), timeout=30
    )
    commit = run_command(("git", "rev-parse", "HEAD"), timeout=30)
    return validate_git_evidence_state(status.stdout, commit.stdout)


def compose_command(env_file: Path, *args: str) -> tuple[str, ...]:
    return ("docker", "compose", "--env-file", str(env_file), *args)


def verify(args: argparse.Namespace) -> Path:
    env_file = args.env_file.resolve()
    values = read_env(env_file)
    environment_issues = validate_compose(values)
    if environment_issues:
        raise ValueError(
            "runtime environment failed safe preflight: " + "; ".join(environment_issues)
        )
    project_name = values.get("COMPOSE_PROJECT_NAME", "")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{2,47}", project_name):
        raise ValueError("COMPOSE_PROJECT_NAME must be an explicit, unique lowercase identifier")

    run_id = validate_run_id(args.run_id)
    backend_base_url = f"http://127.0.0.1:{validated_port(values, 'RECPRO_BACKEND_HOST_PORT')}"
    frontend_base_url = f"http://127.0.0.1:{validated_port(values, 'RECPRO_FRONTEND_HOST_PORT')}"
    git_commit = resolve_clean_git_commit()
    evidence_root = args.evidence_root.resolve()
    try:
        evidence_root.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError("runtime evidence root must stay inside the repository") from exc
    evidence_dir = evidence_root / run_id
    evidence_dir.mkdir(parents=True, exist_ok=False)
    volume_names = (
        f"{project_name}_mysql_data",
        f"{project_name}_neo4j_data",
        f"{project_name}_chroma_data",
    )
    network_names = (f"{project_name}_app", f"{project_name}_data")
    lifecycle: list[dict[str, Any]] = []
    compose_base = compose_command(env_file)
    start_attempted = False
    operation_error: Exception | None = None
    stop_error: Exception | None = None
    operation_phase = "compose_configuration"

    try:
        run_command((*compose_base, "config", "--quiet"), timeout=30)
        operation_phase = "isolated_resource_preflight"
        ensure_new_isolated_runtime(
            compose=compose_base,
            volume_names=volume_names,
            network_names=network_names,
        )
        start_attempted = True
        operation_phase = "initial_start"
        run_command(
            (
                *compose_base,
                "up",
                "--build",
                "--detach",
                "--wait",
                "--wait-timeout",
                str(args.deadline_seconds),
            ),
            timeout=max(180, args.deadline_seconds + 60),
        )
        operation_phase = "first_runtime_health"
        first_runtime = wait_for_runtime(
            compose=compose_base,
            backend_base_url=backend_base_url,
            frontend_base_url=frontend_base_url,
            expected_probe_id=project_name,
            deadline_seconds=args.deadline_seconds,
        )
        operation_phase = "first_volume_identity"
        first_volumes = {
            volume_name: inspect_volume(volume_name) for volume_name in volume_names
        }
        operation_phase = "first_persistence_count"
        first_probe_counts = query_probe_counts(compose_base)
        lifecycle.append(
            {
                "cycle": 1,
                "runtime": first_runtime,
                "volumes": first_volumes,
                "persistence_probe_counts": first_probe_counts,
            }
        )

        operation_phase = "first_safe_stop"
        run_command((*compose_base, "stop"), timeout=120)
        operation_phase = "second_start"
        run_command(
            (
                *compose_base,
                "up",
                "--detach",
                "--wait",
                "--wait-timeout",
                str(args.deadline_seconds),
            ),
            timeout=max(180, args.deadline_seconds + 60),
        )
        operation_phase = "second_runtime_health"
        second_runtime = wait_for_runtime(
            compose=compose_base,
            backend_base_url=backend_base_url,
            frontend_base_url=frontend_base_url,
            expected_probe_id=project_name,
            deadline_seconds=args.deadline_seconds,
        )
        operation_phase = "second_volume_identity"
        second_volumes = {
            volume_name: inspect_volume(volume_name) for volume_name in volume_names
        }
        operation_phase = "second_persistence_count"
        second_probe_counts = query_probe_counts(compose_base)
        lifecycle.append(
            {
                "cycle": 2,
                "runtime": second_runtime,
                "volumes": second_volumes,
                "persistence_probe_counts": second_probe_counts,
            }
        )

        operation_phase = "cross_restart_consistency"
        if first_volumes != second_volumes:
            raise ValueError("named-volume identity changed across safe stop/start")
        if stable_health_signature(first_runtime["direct"]["live"]) != stable_health_signature(
            second_runtime["direct"]["live"]
        ):
            raise ValueError("liveness state changed across safe stop/start")
        if stable_health_signature(first_runtime["direct"]["ready"]) != stable_health_signature(
            second_runtime["direct"]["ready"]
        ):
            raise ValueError("readiness state changed across safe stop/start")
    except Exception as exc:
        operation_error = exc
    finally:
        if start_attempted:
            try:
                run_command((*compose_base, "stop"), timeout=120)
            except (RuntimeError, subprocess.TimeoutExpired) as exc:
                stop_error = exc
                if operation_error is None:
                    operation_phase = "final_safe_stop"
                    operation_error = RuntimeError(
                        "safe Compose stop did not complete; inspect service status without removing data"
                    )

    if operation_error is not None:
        failure_path = evidence_dir / "failure.json"
        write_json_exclusive(
            failure_path,
            {
                "schema_version": "g1-runtime-failure-v1",
                "run_id": run_id,
                "checked_at": datetime.now(UTC).isoformat(),
                "compose_project_name": project_name,
                "failed_phase": operation_phase,
                "operation_error_type": type(operation_error).__name__,
                "operation_error_reason": sanitized_failure_reason(operation_error),
                "completed_lifecycle": lifecycle,
                "safe_stop": {
                    "attempted": start_attempted,
                    "status": (
                        "NOT_ATTEMPTED"
                        if not start_attempted
                        else "FAILED" if stop_error is not None else "COMPLETED"
                    ),
                    "error_type": (
                        type(stop_error).__name__ if stop_error is not None else None
                    ),
                    "error_reason": (
                        sanitized_failure_reason(stop_error)
                        if stop_error is not None
                        else None
                    ),
                },
                "destructive_actions": 0,
                "result": "FAIL",
                "recovery": (
                    "Inspect retained containers and volumes. Do not remove them; use a new "
                    "project name for the next isolated verification run."
                ),
            },
        )
        failure_manifest_path = evidence_dir / "manifest.json"
        write_json_exclusive(
            failure_manifest_path,
            {
                "schema_version": "g1-verification-failure-manifest-v1",
                "run_id": run_id,
                "git_commit": git_commit,
                "compose_project_name": project_name,
                "files": {failure_path.name: file_sha256(failure_path)},
                "destructive_actions": 0,
                "result": "FAIL",
            },
        )
        write_text_exclusive(
            evidence_dir / "SHA256SUMS",
            "".join(
                f"{file_sha256(path)}  {path.name}\n"
                for path in (failure_path, failure_manifest_path)
            ),
        )
        raise operation_error

    evidence = {
        "schema_version": "g1-runtime-evidence-v1",
        "run_id": run_id,
        "checked_at": datetime.now(UTC).isoformat(),
        "compose_project_name": project_name,
        "verifier_database_sql_actions": {
            "read_only_selects": 4,
            "writes": 0,
            "updates": 0,
            "deletes": 0,
            "ddl": 0,
        },
        "compose_new_volume_initialization": (
            "MySQL creates the isolated database, a platform persistence-probe table, "
            "one append-only marker row, a runtime user, and SELECT/INSERT grants."
        ),
        "destructive_actions": 0,
        "cycles": lifecycle,
        "result": "PASS",
    }
    runtime_path = evidence_dir / "runtime-verification.json"
    write_json_exclusive(runtime_path, evidence)

    sanitized_environment = {
        key: values[key]
        for key in (
            "COMPOSE_PROJECT_NAME",
            "RECPRO_APP_ENV",
            "RECPRO_CONFIG_BUNDLE_VERSION",
            "RECPRO_CONFIG_BUNDLE_PATH",
            "RECPRO_CONFIG_BUNDLE_SHA256",
            "RECPRO_MYSQL_DATABASE",
            "RECPRO_MYSQL_USER",
            "RECPRO_PERSISTENCE_PROBE_ID",
            "RECPRO_BACKEND_HOST_PORT",
            "RECPRO_FRONTEND_HOST_PORT",
        )
        if key in values
    }
    environment_path = evidence_dir / "environment-sanitized.json"
    write_json_exclusive(environment_path, sanitized_environment)

    commands_path = evidence_dir / "commands.json"
    write_json_exclusive(
        commands_path,
        {
            "commands": [
                "docker compose config --quiet",
                "docker compose up --build --detach --wait",
                "HTTP GET direct and frontend-proxied health endpoints",
                "docker inspect service state and restart count",
                "docker volume inspect three named volumes",
                "two read-only SELECT count queries before each safe stop",
                "docker compose stop",
                "docker compose up --detach --wait",
                "docker compose stop",
            ],
            "cleanup_commands": 0,
            "database_client_commands": 2,
        },
    )

    before_counts_path = evidence_dir / "data-counts-before-restart.json"
    after_counts_path = evidence_dir / "data-counts-after-restart.json"
    before_marker_counts = {
        "table": "recpro_runtime_probe",
        "probe_id": project_name,
        **lifecycle[0]["persistence_probe_counts"],
    }
    after_marker_counts = {
        "table": "recpro_runtime_probe",
        "probe_id": project_name,
        **lifecycle[1]["persistence_probe_counts"],
    }
    write_json_exclusive(before_counts_path, before_marker_counts)
    write_json_exclusive(after_counts_path, after_marker_counts)

    evidence_files = (
        runtime_path,
        environment_path,
        commands_path,
        before_counts_path,
        after_counts_path,
    )
    hashes = {path.name: file_sha256(path) for path in evidence_files}
    manifest_path = evidence_dir / "manifest.json"
    write_json_exclusive(
        manifest_path,
        {
            "schema_version": "g1-verification-manifest-v1",
            "run_id": run_id,
            "git_commit": git_commit,
            "config_bundle_version": values["RECPRO_CONFIG_BUNDLE_VERSION"],
            "config_bundle_sha256": values["RECPRO_CONFIG_BUNDLE_SHA256"],
            "persistence_probe_id": project_name,
            "files": hashes,
            "destructive_actions": 0,
        },
    )
    checksum_lines = [
        f"{file_sha256(path)}  {path.name}"
        for path in (*evidence_files, manifest_path)
    ]
    write_text_exclusive(
        evidence_dir / "SHA256SUMS",
        "\n".join(checksum_lines) + "\n",
    )
    return evidence_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--env-file", type=Path, default=PROJECT_ROOT / ".env.compose"
    )
    parser.add_argument(
        "--evidence-root",
        type=Path,
        default=PROJECT_ROOT / "artifacts" / "verification" / "g1",
    )
    parser.add_argument(
        "--deadline-seconds",
        type=int,
        choices=range(30, 301),
        default=120,
        metavar="30..300",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        evidence_dir = verify(args)
    except (OSError, ValueError, RuntimeError, TimeoutError, subprocess.TimeoutExpired) as exc:
        print(f"[FAIL] {exc}")
        return 1
    print(f"[PASS] G1 runtime restart evidence: {evidence_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
