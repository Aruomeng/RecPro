#!/usr/bin/env python3
"""Verify a G8 six-browser-scenario plan without opening a business request."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Sequence

from jsonschema import Draft202012Validator, FormatChecker

from scripts.build_g8_browser_scenario_plan import PROJECT_ROOT, SCHEMA_PATH, canonical


def resolve_inside_project(path: Path) -> Path:
    resolved = (path if path.is_absolute() else PROJECT_ROOT / path).resolve(strict=True)
    try:
        resolved.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError("plan must resolve inside the repository") from exc
    return resolved


def current_commit() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, check=True, capture_output=True, text=True).stdout.strip()


def validate_plan(payload: dict[str, Any], *, expected_commit: str | None = None) -> dict[str, Any]:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(payload), key=lambda error: tuple(error.absolute_path))
    if errors:
        raise ValueError("browser scenario plan schema failed: " + "; ".join(error.message for error in errors))
    unsigned = dict(payload)
    plan_hash = str(unsigned.pop("plan_hash"))
    if hashlib.sha256(canonical(unsigned)).hexdigest() != plan_hash:
        raise ValueError("browser scenario plan canonical hash is invalid")
    if expected_commit is not None and payload["git_commit"] != expected_commit:
        raise ValueError("browser scenario plan is bound to a different Git commit")
    if payload["scenario_ids"] != [item["scenario_id"] for item in payload["scenarios"]]:
        raise ValueError("scenario_ids order does not match scenario objects")
    fixture_users = [item["fixture_user"] for item in payload["scenarios"]]
    if len(set(fixture_users)) != 6:
        raise ValueError("six browser scenarios must use six distinct fixture identities")
    request_ids = [item["request"]["request_id"] for item in payload["scenarios"]]
    session_ids = [item["request"]["session_id"] for item in payload["scenarios"]]
    if len(set(request_ids)) != 6 or len(set(session_ids)) != 6:
        raise ValueError("browser request and session identities must be unique")
    if payload["aggregate_budget"]["max_outbox_claims"] != 0 or payload["safety_assertions"]["business_writes_authorized"]:
        raise ValueError("browser plan cannot authorize Outbox claims or business writes")
    if any(item["budget"]["max_outbox_claims"] != 0 or not item["budget"]["replay_zero_delta"] for item in payload["scenarios"]):
        raise ValueError("every browser scenario must require zero-delta replay and zero Outbox claims")
    if payload["environment"]["llm_provider"] != "deepseek" or payload["environment"]["llm_model"] != "deepseek-v4-flash":
        raise ValueError("browser plan must freeze the configured DeepSeek model")
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--allow-stale-commit", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        path = resolve_inside_project(args.plan)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("browser plan must be a JSON object")
        validate_plan(payload, expected_commit=None if args.allow_stale_commit else current_commit())
        print(json.dumps({"status": "PASS", "path": path.relative_to(PROJECT_ROOT).as_posix(), "plan_id": payload["plan_id"], "plan_hash": payload["plan_hash"], "git_commit": payload["git_commit"], "scenario_count": len(payload["scenarios"]), "database_writes": 0, "external_llm_requests": 0, "outbox_claims": 0, "files_deleted": 0, "database_physical_deletions": 0}, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "FAIL", "error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
