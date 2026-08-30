"""Read-only validation for local G1 runtime environment files."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Mapping, Sequence
from urllib.parse import urlsplit


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{2,47}$")
DATABASE_IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
MYSQL_USER_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,31}$")
LOCAL_SECRET_PATTERN = re.compile(r"^[A-Za-z0-9._~-]{16,128}$")
SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
LLM_KEY_PATTERN = re.compile(r"^\S{16,256}$")
WORKER_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
WORKER_FORMULA_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
DEFAULT_PROMPT_BUNDLE_PATH = "contracts/prompts/rec-prompts-v1.0.1.json"
DEFAULT_PROMPT_BUNDLE_SHA256 = (
    "1fa3b19788574189ae1680a0ef5565fd378200d146d9c0ba83da583ba3abce1a"
)
EXAMPLE_PROJECT_NAME = "libramas-g1-researcher01-local01"
PORT_KEYS = (
    "RECPRO_MYSQL_PORT",
    "RECPRO_MYSQL_HOST_PORT",
    "RECPRO_NEO4J_HTTP_HOST_PORT",
    "RECPRO_NEO4J_BOLT_HOST_PORT",
    "RECPRO_BACKEND_HOST_PORT",
    "RECPRO_FRONTEND_HOST_PORT",
    "RECPRO_BACKEND_PORT",
)


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not key.strip():
            raise ValueError(f"invalid environment syntax at line {line_number}")
        normalized_key = key.strip()
        if normalized_key in values:
            raise ValueError(f"duplicate environment key: {normalized_key}")
        values[normalized_key] = value.strip().strip('"').strip("'")
    return values


def _missing(values: Mapping[str, str], required: set[str]) -> list[str]:
    return sorted(key for key in required if not values.get(key, "").strip())


def validate_llm(values: Mapping[str, str]) -> tuple[str, ...]:
    """Validate optional LLM and Prompt settings without exposing secrets."""

    issues: list[str] = []
    provider = values.get("RECPRO_LLM_PROVIDER", "mock").strip()
    if provider not in {"mock", "deepseek"}:
        issues.append("RECPRO_LLM_PROVIDER must be mock or deepseek")

    base_url = values.get("RECPRO_LLM_BASE_URL", "https://api.deepseek.com").strip()
    parsed = urlsplit(base_url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
        issues.append("RECPRO_LLM_BASE_URL must be an HTTPS origin without path, query, or fragment")

    api_key = values.get("RECPRO_LLM_API_KEY", "")
    if provider == "deepseek" and not api_key.strip():
        issues.append("RECPRO_LLM_API_KEY is required when RECPRO_LLM_PROVIDER=deepseek")
    if api_key and not LLM_KEY_PATTERN.fullmatch(api_key):
        issues.append("RECPRO_LLM_API_KEY must be 16-256 non-whitespace characters")

    timeout_text = values.get("RECPRO_LLM_TIMEOUT_SECONDS", "20")
    try:
        timeout = float(timeout_text)
    except ValueError:
        issues.append("RECPRO_LLM_TIMEOUT_SECONDS must be numeric")
    else:
        if not 0 < timeout <= 120:
            issues.append("RECPRO_LLM_TIMEOUT_SECONDS must be greater than 0 and at most 120")

    token_text = values.get("RECPRO_LLM_MAX_OUTPUT_TOKENS", "512")
    try:
        tokens = int(token_text)
    except ValueError:
        issues.append("RECPRO_LLM_MAX_OUTPUT_TOKENS must be an integer")
    else:
        if not 1 <= tokens <= 8192:
            issues.append("RECPRO_LLM_MAX_OUTPUT_TOKENS must be between 1 and 8192")

    prompt_path = values.get("RECPRO_PROMPT_BUNDLE_PATH", DEFAULT_PROMPT_BUNDLE_PATH)
    prompt_candidate = Path(prompt_path)
    if prompt_candidate.is_absolute() or ".." in prompt_candidate.parts:
        issues.append("RECPRO_PROMPT_BUNDLE_PATH must stay inside the repository")
    prompt_hash = values.get("RECPRO_PROMPT_BUNDLE_SHA256", DEFAULT_PROMPT_BUNDLE_SHA256)
    if not SHA256_PATTERN.fullmatch(prompt_hash):
        issues.append("RECPRO_PROMPT_BUNDLE_SHA256 must be 64 lowercase hex characters")
    prompt_version = values.get("RECPRO_PROMPT_BUNDLE_VERSION", "prompt-v1")
    if not re.fullmatch(r"^[A-Za-z0-9][A-Za-z0-9._-]*$", prompt_version):
        issues.append("RECPRO_PROMPT_BUNDLE_VERSION has an unsafe format")
    return tuple(issues)


def validate_worker(values: Mapping[str, str]) -> tuple[str, ...]:
    """Validate the worker deployment boundary without connecting to MySQL."""

    issues: list[str] = []
    enabled = values.get("RECPRO_WORKER_ENABLED", "false").strip().lower()
    if enabled not in {"true", "false"}:
        issues.append("RECPRO_WORKER_ENABLED must be true or false")
    mode = values.get("RECPRO_WORKER_MODE", "disabled").strip()
    if mode not in {"disabled", "profile_outbox"}:
        issues.append("RECPRO_WORKER_MODE must be disabled or profile_outbox")
    if enabled == "true" and mode != "profile_outbox":
        issues.append("RECPRO_WORKER_MODE must be profile_outbox when the worker is enabled")
    if enabled == "false" and mode != "disabled":
        issues.append("RECPRO_WORKER_MODE must be disabled when the worker is disabled")
    if enabled == "true" and values.get("RECPRO_APP_ENV", "development") == "production":
        issues.append("the Profile Outbox worker is not enabled for production yet")

    worker_id = values.get("RECPRO_WORKER_ID", "recpro-worker").strip()
    if not WORKER_ID_PATTERN.fullmatch(worker_id):
        issues.append("RECPRO_WORKER_ID has an unsafe format")
    formula_version = values.get("RECPRO_WORKER_FORMULA_VERSION", "profile-g2-v1").strip()
    if not WORKER_FORMULA_PATTERN.fullmatch(formula_version):
        issues.append("RECPRO_WORKER_FORMULA_VERSION has an unsafe format")

    numeric_limits = {
        "RECPRO_WORKER_POLL_INTERVAL_SECONDS": (float, 0.0, 60.0),
        "RECPRO_WORKER_BATCH_LIMIT": (int, 1, 100),
        "RECPRO_WORKER_LEASE_SECONDS": (int, 1, 3600),
        "RECPRO_WORKER_MAX_ATTEMPTS": (int, 1, 10),
    }
    for key, (converter, lower, upper) in numeric_limits.items():
        raw_value = values.get(key, "")
        if not raw_value:
            continue
        try:
            number = converter(raw_value)
        except (TypeError, ValueError):
            issues.append(f"{key} has an invalid numeric value")
            continue
        in_range = (
            lower < number <= upper
            if converter is float
            else lower <= number <= upper
        )
        if not in_range:
            issues.append(f"{key} is outside its safe range")
    return tuple(issues)


def validate_mysql_pool(values: Mapping[str, str]) -> tuple[str, ...]:
    """Validate optional pool bounds before a process can open sockets."""

    issues: list[str] = []
    numeric_limits = {
        "RECPRO_MYSQL_POOL_MIN_SIZE": (int, 0, 32),
        "RECPRO_MYSQL_POOL_MAX_SIZE": (int, 1, 64),
        "RECPRO_MYSQL_POOL_RECYCLE_SECONDS": (int, 60, 86400),
        "RECPRO_MYSQL_POOL_ACQUIRE_TIMEOUT_SECONDS": (float, 0.0, 30.0),
    }
    parsed: dict[str, int | float] = {}
    for key, (converter, lower, upper) in numeric_limits.items():
        raw_value = values.get(key, "")
        if not raw_value:
            continue
        try:
            number = converter(raw_value)
        except (TypeError, ValueError):
            issues.append(f"{key} has an invalid numeric value")
            continue
        if converter is float:
            valid = lower < number <= upper
        else:
            valid = lower <= number <= upper
        if not valid:
            issues.append(f"{key} is outside its safe range")
            continue
        parsed[key] = number
    minimum = parsed.get("RECPRO_MYSQL_POOL_MIN_SIZE")
    maximum = parsed.get("RECPRO_MYSQL_POOL_MAX_SIZE")
    if minimum is not None and maximum is not None and minimum > maximum:
        issues.append("RECPRO_MYSQL_POOL_MIN_SIZE cannot exceed RECPRO_MYSQL_POOL_MAX_SIZE")
    return tuple(issues)


def validate_common(values: Mapping[str, str]) -> tuple[str, ...]:
    issues: list[str] = []
    issues.extend(validate_llm(values))
    issues.extend(validate_worker(values))
    issues.extend(validate_mysql_pool(values))
    required = {
        "RECPRO_CONFIG_BUNDLE_VERSION",
        "RECPRO_CONFIG_BUNDLE_PATH",
        "RECPRO_CONFIG_BUNDLE_SHA256",
        "RECPRO_MYSQL_DATABASE",
        "RECPRO_MYSQL_USER",
        "RECPRO_MYSQL_PASSWORD",
        "RECPRO_MYSQL_MIGRATION_USER",
        "RECPRO_MYSQL_MIGRATION_PASSWORD",
        "RECPRO_PERSISTENCE_PROBE_ID",
    }
    for key in _missing(values, required):
        issues.append(f"required value is empty: {key}")

    database = values.get("RECPRO_MYSQL_DATABASE", "")
    user = values.get("RECPRO_MYSQL_USER", "")
    password = values.get("RECPRO_MYSQL_PASSWORD", "")
    migration_user = values.get("RECPRO_MYSQL_MIGRATION_USER", "")
    migration_password = values.get("RECPRO_MYSQL_MIGRATION_PASSWORD", "")
    if database and not DATABASE_IDENTIFIER_PATTERN.fullmatch(database):
        issues.append("RECPRO_MYSQL_DATABASE has an unsafe identifier format")
    if user and not MYSQL_USER_PATTERN.fullmatch(user):
        issues.append("RECPRO_MYSQL_USER has an unsafe identifier format")
    if migration_user and not MYSQL_USER_PATTERN.fullmatch(migration_user):
        issues.append("RECPRO_MYSQL_MIGRATION_USER has an unsafe identifier format")
    if migration_user and migration_user == user:
        issues.append("RECPRO_MYSQL_MIGRATION_USER must differ from RECPRO_MYSQL_USER")
    if password and not LOCAL_SECRET_PATTERN.fullmatch(password):
        issues.append("RECPRO_MYSQL_PASSWORD does not meet the local secret format")
    if migration_password and not LOCAL_SECRET_PATTERN.fullmatch(migration_password):
        issues.append("RECPRO_MYSQL_MIGRATION_PASSWORD does not meet the local secret format")

    bundle_hash = values.get("RECPRO_CONFIG_BUNDLE_SHA256", "")
    if bundle_hash and not SHA256_PATTERN.fullmatch(bundle_hash):
        issues.append("RECPRO_CONFIG_BUNDLE_SHA256 must be 64 lowercase hex characters")
    bundle_path = values.get("RECPRO_CONFIG_BUNDLE_PATH", "")
    if bundle_path:
        candidate = Path(bundle_path)
        if candidate.is_absolute() or ".." in candidate.parts:
            issues.append("RECPRO_CONFIG_BUNDLE_PATH must stay inside the repository")

    probe_id = values.get("RECPRO_PERSISTENCE_PROBE_ID", "")
    if probe_id and not PROJECT_PATTERN.fullmatch(probe_id):
        issues.append("RECPRO_PERSISTENCE_PROBE_ID has an unsafe format")

    for key in PORT_KEYS:
        raw_value = values.get(key, "")
        if not raw_value:
            continue
        try:
            port = int(raw_value)
        except ValueError:
            issues.append(f"{key} must be an integer port")
        else:
            if not 1 <= port <= 65535:
                issues.append(f"{key} must be between 1 and 65535")

    raw_timeout = values.get("RECPRO_MYSQL_CONNECT_TIMEOUT_SECONDS", "")
    if raw_timeout:
        try:
            timeout = float(raw_timeout)
        except ValueError:
            issues.append("RECPRO_MYSQL_CONNECT_TIMEOUT_SECONDS must be numeric")
        else:
            if not 0 < timeout <= 30:
                issues.append(
                    "RECPRO_MYSQL_CONNECT_TIMEOUT_SECONDS must be greater than 0 and at most 30"
                )
    return tuple(issues)


def validate_compose(values: Mapping[str, str]) -> tuple[str, ...]:
    issues = list(validate_common(values))
    required = {
        "COMPOSE_PROJECT_NAME",
        "RECPRO_MYSQL_ROOT_PASSWORD",
        "RECPRO_NEO4J_USER",
        "RECPRO_NEO4J_PASSWORD",
    }
    for key in _missing(values, required):
        issues.append(f"required value is empty: {key}")

    project_name = values.get("COMPOSE_PROJECT_NAME", "")
    if project_name and not PROJECT_PATTERN.fullmatch(project_name):
        issues.append("COMPOSE_PROJECT_NAME has an unsafe format")
    if project_name == EXAMPLE_PROJECT_NAME:
        issues.append("COMPOSE_PROJECT_NAME still uses the checked-in placeholder")
    probe_id = values.get("RECPRO_PERSISTENCE_PROBE_ID", "")
    if project_name and probe_id and probe_id != project_name:
        issues.append("RECPRO_PERSISTENCE_PROBE_ID must equal COMPOSE_PROJECT_NAME")

    if values.get("RECPRO_MYSQL_HOST") != "mysql":
        issues.append("compose-mode MySQL host must be the isolated mysql service")

    neo4j_user = values.get("RECPRO_NEO4J_USER", "")
    if neo4j_user and neo4j_user != "neo4j":
        issues.append("RECPRO_NEO4J_USER must be neo4j for the pinned Community image")

    for key in (
        "RECPRO_MYSQL_ROOT_PASSWORD",
        "RECPRO_MYSQL_MIGRATION_PASSWORD",
        "RECPRO_NEO4J_PASSWORD",
    ):
        value = values.get(key, "")
        if value and not LOCAL_SECRET_PATTERN.fullmatch(value):
            issues.append(f"{key} does not meet the local secret format")

    secret_values = [
        values.get("RECPRO_MYSQL_PASSWORD", ""),
        values.get("RECPRO_MYSQL_MIGRATION_PASSWORD", ""),
        values.get("RECPRO_MYSQL_ROOT_PASSWORD", ""),
        values.get("RECPRO_NEO4J_PASSWORD", ""),
    ]
    populated = [value for value in secret_values if value]
    if len(populated) != len(set(populated)):
        issues.append("runtime, bootstrap, and Neo4j secrets must be distinct")

    host_port_keys = (
        "RECPRO_MYSQL_HOST_PORT",
        "RECPRO_NEO4J_HTTP_HOST_PORT",
        "RECPRO_NEO4J_BOLT_HOST_PORT",
        "RECPRO_BACKEND_HOST_PORT",
        "RECPRO_FRONTEND_HOST_PORT",
    )
    populated_ports = [values[key] for key in host_port_keys if values.get(key)]
    if len(populated_ports) != len(set(populated_ports)):
        issues.append("Compose host ports must be distinct")
    return tuple(issues)


def validate_host(values: Mapping[str, str]) -> tuple[str, ...]:
    issues = list(validate_common(values))
    if values.get("RECPRO_MYSQL_HOST") not in {"127.0.0.1", "localhost"}:
        issues.append("host-mode MySQL must resolve to the local machine")
    if values.get("RECPRO_PERSISTENCE_PROBE_ID") == EXAMPLE_PROJECT_NAME:
        issues.append("host-mode persistence probe still uses the checked-in placeholder")
    return tuple(issues)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("compose", "host"), required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        values = read_env(args.env_file.resolve())
    except (OSError, ValueError) as exc:
        print(f"[FAIL] runtime environment cannot be parsed: {exc}")
        return 2
    issues = validate_compose(values) if args.mode == "compose" else validate_host(values)
    if issues:
        for issue in issues:
            print(f"[FAIL] {issue}")
        return 2
    print(f"[PASS] {args.mode} environment is structurally safe (secret values not displayed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
