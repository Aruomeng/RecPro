"""Read-only verification for the explicit Profile Outbox worker wiring.

This gate inspects Compose and environment contracts only.  It never opens a
database connection, starts a container, claims an Outbox row, or calls an
external provider.  The default report must prove that the worker remains
disabled until both opt-in settings are selected.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Mapping

from backend.app.config import AppSettings
from scripts.validate_runtime_env import read_env, validate_compose


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")


def validate_run_id(value: str) -> str:
    if RUN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("run id must use 3-64 safe characters")
    return value


def _read_worker_settings(values: Mapping[str, str]) -> AppSettings:
    """Build settings from explicit values without inheriting process secrets."""

    return AppSettings(
        app_env=values.get("RECPRO_APP_ENV", "development"),
        config_bundle_version=values.get("RECPRO_CONFIG_BUNDLE_VERSION", "rec-1.0.0"),
        config_bundle_path=values.get(
            "RECPRO_CONFIG_BUNDLE_PATH", "contracts/config/examples/rec-1.0.0.json"
        ),
        config_bundle_sha256=values.get("RECPRO_CONFIG_BUNDLE_SHA256", ""),
        prompt_bundle_version=values.get("RECPRO_PROMPT_BUNDLE_VERSION", "prompt-v1"),
        prompt_bundle_path=values.get(
            "RECPRO_PROMPT_BUNDLE_PATH", "contracts/prompts/rec-prompts-v1.0.1.json"
        ),
        prompt_bundle_sha256=values.get("RECPRO_PROMPT_BUNDLE_SHA256", ""),
        mysql_host=values.get("RECPRO_MYSQL_HOST", "mysql"),
        mysql_port=int(values.get("RECPRO_MYSQL_PORT", "3306")),
        mysql_database=values.get("RECPRO_MYSQL_DATABASE", "recpro"),
        mysql_user=values.get("RECPRO_MYSQL_USER", "recpro_runtime"),
        mysql_password=values.get("RECPRO_MYSQL_PASSWORD", "placeholder-secret-001"),
        mysql_connect_timeout_seconds=float(
            values.get("RECPRO_MYSQL_CONNECT_TIMEOUT_SECONDS", "3")
        ),
        persistence_probe_id=values.get("RECPRO_PERSISTENCE_PROBE_ID", "g1-bootstrap-v1"),
        worker_enabled=values.get("RECPRO_WORKER_ENABLED", "false").lower() == "true",
        worker_mode=values.get("RECPRO_WORKER_MODE", "disabled"),
        worker_id=values.get("RECPRO_WORKER_ID", "recpro-worker"),
        worker_poll_interval_seconds=float(
            values.get("RECPRO_WORKER_POLL_INTERVAL_SECONDS", "5")
        ),
        worker_batch_limit=int(values.get("RECPRO_WORKER_BATCH_LIMIT", "10")),
        worker_lease_seconds=int(values.get("RECPRO_WORKER_LEASE_SECONDS", "60")),
        worker_max_attempts=int(values.get("RECPRO_WORKER_MAX_ATTEMPTS", "3")),
        worker_formula_version=values.get(
            "RECPRO_WORKER_FORMULA_VERSION", "profile-g2-v1"
        ),
        llm_provider="mock",
        llm_api_key=None,
    )


def build_report(*, run_id: str, env_file: Path) -> dict[str, object]:
    run_id = validate_run_id(run_id)
    values = read_env(env_file.resolve())
    issues = validate_compose(values)
    if issues:
        raise ValueError("environment validation failed: " + "; ".join(issues))

    compose_text = (PROJECT_ROOT / "compose.yaml").read_text(encoding="utf-8")
    required_markers = (
        '"${RECPRO_WORKER_ENABLED:-false}"',
        '"${RECPRO_WORKER_MODE:-disabled}"',
        '"${RECPRO_WORKER_ID:-recpro-worker}"',
        '"${RECPRO_WORKER_BATCH_LIMIT:-10}"',
        '"backend.app.worker"',
    )
    missing_markers = [marker for marker in required_markers if marker not in compose_text]
    if missing_markers:
        raise ValueError(f"Compose worker contract is missing markers: {missing_markers}")

    settings = _read_worker_settings(values)
    if settings.worker_enabled or settings.worker_mode != "disabled":
        raise ValueError(
            "the supplied default environment would enable a controlled worker; "
            "use an explicit opt-in verification instead"
        )

    return {
        "status": "PASS",
        "run_id": run_id,
        "env_file": str(env_file.resolve().relative_to(PROJECT_ROOT)),
        "worker": {
            "enabled": settings.worker_enabled,
            "mode": settings.worker_mode,
            "worker_id": settings.worker_id,
            "batch_limit": settings.worker_batch_limit,
            "lease_seconds": settings.worker_lease_seconds,
            "max_attempts": settings.worker_max_attempts,
            "formula_version": settings.worker_formula_version,
        },
        "compose_markers": len(required_markers),
        "database_connections": 0,
        "database_writes": 0,
        "outbox_claims": 0,
        "external_requests": 0,
        "actual_delete_count": 0,
        "files_deleted": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.compose")
    args = parser.parse_args()
    report = build_report(run_id=args.run_id, env_file=args.env_file)
    output_dir = PROJECT_ROOT / "artifacts" / "verification" / "g5" / args.run_id
    output_dir.mkdir(parents=True, exist_ok=False)
    output_path = output_dir / "worker-wiring.json"
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    print(f"evidence={output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
