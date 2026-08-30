"""Safely synchronize host-mode local settings from the reviewed Compose env.

The populated environment files are intentionally ignored by Git.  This tool
keeps the host file's comments and existing keys, copies only the approved
runtime values from the isolated Compose file, and refuses to modify anything
unless ``--apply`` is supplied.  Secret values are never printed.

No database connection is opened and no database or repository file is
deleted.  When applying, a 0600 backup is copied to ``/tmp`` before the host
file is rewritten so the previous local configuration remains recoverable.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
from typing import Mapping, Sequence

from scripts.validate_runtime_env import read_env, validate_compose, validate_host


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")

# These values are deliberately copied from the isolated Compose runtime.  The
# host process must use the published loopback port and the same least-privilege
# runtime/migration identities; Compose's service hostname is not reachable
# from a host process.
REQUIRED_COMPOSE_KEYS = (
    "COMPOSE_PROJECT_NAME",
    "RECPRO_MYSQL_HOST_PORT",
    "RECPRO_MYSQL_DATABASE",
    "RECPRO_MYSQL_USER",
    "RECPRO_MYSQL_PASSWORD",
    "RECPRO_MYSQL_MIGRATION_USER",
    "RECPRO_MYSQL_MIGRATION_PASSWORD",
)
COPY_KEYS = (
    "RECPRO_MYSQL_DATABASE",
    "RECPRO_MYSQL_USER",
    "RECPRO_MYSQL_PASSWORD",
    "RECPRO_MYSQL_MIGRATION_USER",
    "RECPRO_MYSQL_MIGRATION_PASSWORD",
    "RECPRO_MYSQL_CONNECT_TIMEOUT_SECONDS",
    "RECPRO_MYSQL_POOL_MIN_SIZE",
    "RECPRO_MYSQL_POOL_MAX_SIZE",
    "RECPRO_MYSQL_POOL_RECYCLE_SECONDS",
    "RECPRO_MYSQL_POOL_ACQUIRE_TIMEOUT_SECONDS",
    "RECPRO_LLM_PROVIDER",
    "RECPRO_LLM_BASE_URL",
    "RECPRO_LLM_MODEL",
    "RECPRO_LLM_API_KEY",
    "RECPRO_LLM_TIMEOUT_SECONDS",
    "RECPRO_LLM_MAX_OUTPUT_TOKENS",
    "RECPRO_PROMPT_BUNDLE_VERSION",
    "RECPRO_PROMPT_BUNDLE_PATH",
    "RECPRO_PROMPT_BUNDLE_SHA256",
)
EXPLICIT_HOST_VALUES = {
    "RECPRO_MYSQL_HOST": "127.0.0.1",
    "RECPRO_DEMO_HTTP_ENABLED": "false",
    "RECPRO_AUTH_ENABLED": "false",
    "RECPRO_PRODUCTION_HTTP_ENABLED": "false",
    "RECPRO_G4_HTTP_ENABLED": "false",
    "RECPRO_G5_INTERACTION_HTTP_ENABLED": "false",
    "RECPRO_DEBUG_API_ENABLED": "false",
}


def validate_run_id(value: str) -> str:
    if RUN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("run id must use 3-64 safe characters")
    return value


def parse_assignments(path: Path) -> list[tuple[str, int]]:
    assignments: list[tuple[str, int]] = []
    seen: set[str] = set()
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, separator, _ = raw_line.partition("=")
        if not separator or not key.strip():
            raise ValueError(f"invalid environment syntax at line {line_number}")
        normalized = key.strip()
        if normalized in seen:
            raise ValueError(f"duplicate environment key: {normalized}")
        seen.add(normalized)
        assignments.append((normalized, line_number))
    return assignments


def build_overrides(compose_values: Mapping[str, str]) -> dict[str, str]:
    missing = [key for key in REQUIRED_COMPOSE_KEYS if not compose_values.get(key, "").strip()]
    if missing:
        raise ValueError("Compose environment is missing required values: " + ", ".join(missing))
    overrides = dict(EXPLICIT_HOST_VALUES)
    overrides["RECPRO_MYSQL_PORT"] = compose_values["RECPRO_MYSQL_HOST_PORT"]
    overrides["RECPRO_PERSISTENCE_PROBE_ID"] = compose_values["COMPOSE_PROJECT_NAME"]
    for key in COPY_KEYS:
        value = compose_values.get(key, "")
        if value.strip():
            overrides[key] = value
    return overrides


def render_env(original: str, overrides: Mapping[str, str]) -> tuple[str, tuple[str, ...]]:
    lines = original.splitlines()
    present: set[str] = set()
    changed: list[str] = []
    rendered: list[str] = []
    for raw_line in lines:
        key, separator, _ = raw_line.partition("=")
        normalized = key.strip() if separator and key.strip() else ""
        if normalized and normalized in overrides:
            rendered.append(f"{normalized}={overrides[normalized]}")
            present.add(normalized)
            changed.append(normalized)
        else:
            rendered.append(raw_line)
            if normalized:
                present.add(normalized)
    missing = [key for key in overrides if key not in present]
    if missing:
        if rendered and rendered[-1] != "":
            rendered.append("")
        rendered.extend(f"{key}={overrides[key]}" for key in missing)
        changed.extend(missing)
    return "\n".join(rendered).rstrip("\n") + "\n", tuple(dict.fromkeys(changed))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--compose-file", type=Path, default=PROJECT_ROOT / ".env.compose")
    parser.add_argument("--host-file", type=Path, default=PROJECT_ROOT / ".env.host")
    parser.add_argument("--apply", action="store_true")
    return parser


def execute(args: argparse.Namespace) -> int:
    run_id = validate_run_id(args.run_id)
    compose_path = args.compose_file.resolve(strict=True)
    host_path = args.host_file.resolve(strict=True)
    compose_values = read_env(compose_path)
    host_values = read_env(host_path)
    compose_issues = validate_compose(compose_values)
    if compose_issues:
        raise ValueError("Compose environment failed safe preflight: " + "; ".join(compose_issues))
    overrides = build_overrides(compose_values)
    parse_assignments(host_path)
    rendered, changed = render_env(host_path.read_text(encoding="utf-8"), overrides)
    preview_values = read_env_from_text(rendered)
    host_issues = validate_host(preview_values)
    if host_issues:
        raise ValueError("synchronized host environment failed safe preflight: " + "; ".join(host_issues))

    backup_path: Path | None = None
    if args.apply:
        backup_path = Path("/tmp") / f"recpro-env-host-before-{run_id}"
        if backup_path.exists():
            raise FileExistsError(f"refusing to overwrite existing backup: {backup_path}")
        shutil.copy2(host_path, backup_path)
        os.chmod(backup_path, 0o600)
        host_path.write_text(rendered, encoding="utf-8")
        os.chmod(host_path, 0o600)

    payload = {
        "run_id": run_id,
        "mode": "APPLY" if args.apply else "DRY_RUN",
        "compose_file": str(compose_path),
        "host_file": str(host_path),
        "changed_keys": list(changed),
        "host_preflight": "PASS",
        "backup_path": str(backup_path) if backup_path else None,
        "database_writes": 0,
        "external_requests": 0,
        "files_deleted": 0,
        "overwritten_inputs": 0,
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


def read_env_from_text(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not key.strip():
            raise ValueError(f"invalid rendered environment syntax at line {line_number}")
        normalized = key.strip()
        if normalized in values:
            raise ValueError(f"duplicate rendered environment key: {normalized}")
        values[normalized] = value.strip().strip('"').strip("'")
    return values


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return execute(args)
    except (OSError, ValueError, FileExistsError) as exc:
        print(f"[FAIL] host environment synchronization stopped: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
