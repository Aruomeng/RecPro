"""Run a pure, fail-closed production Compose preflight.

The command reads only non-secret deployment facts from the environment and
never contacts MySQL, Neo4j, Chroma, an OIDC provider or DeepSeek.  It is safe
to run before a ChangePlan is approved.  A report path, when supplied, must
not already exist; no existing evidence is overwritten.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Sequence

try:
    from backend.app.platform.production import (
        ProductionGateContext,
        evaluate_production_gate,
    )
    from scripts.evaluation_runtime import write_json_exclusive
except ModuleNotFoundError:  # direct ``python scripts/...`` execution
    from backend.app.platform.production import ProductionGateContext, evaluate_production_gate
    from evaluation_runtime import write_json_exclusive


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() == "true"


def build_context() -> ProductionGateContext:
    """Build context from public flags; secret values are never read."""

    return ProductionGateContext(
        app_env=os.environ.get("RECPRO_APP_ENV", "").strip().lower(),
        production_http_enabled=_flag("RECPRO_PRODUCTION_HTTP_ENABLED"),
        auth_enabled=_flag("RECPRO_AUTH_ENABLED"),
        auth_mode=os.environ.get("RECPRO_AUTH_MODE", "").strip().lower(),
        oidc_issuer=os.environ.get("RECPRO_OIDC_ISSUER") or None,
        oidc_audience=os.environ.get("RECPRO_OIDC_AUDIENCE") or None,
        oidc_jwks_uri=os.environ.get("RECPRO_OIDC_JWKS_URI") or None,
        jwks_fetcher_configured=_flag("RECPRO_OIDC_FETCHER_CONFIGURED"),
        oidc_identity_mapper_configured=_flag("RECPRO_OIDC_MAPPER_CONFIGURED"),
        tls_termination_enabled=_flag("RECPRO_TLS_TERMINATION_ENABLED"),
        secure_cookies=_flag("RECPRO_AUTH_COOKIE_SECURE"),
        runtime_database_user=os.environ.get("RECPRO_MYSQL_USER") or None,
        graph_readonly_user=os.environ.get("RECPRO_NEO4J_READ_USER") or None,
        recommendation_api_enabled=_flag("RECPRO_RECOMMENDATION_API_ENABLED"),
        feedback_api_enabled=_flag("RECPRO_FEEDBACK_API_ENABLED"),
        behavior_api_enabled=_flag("RECPRO_BEHAVIOR_API_ENABLED"),
        readiness_confirmed=_flag("RECPRO_READINESS_CONFIRMED"),
        backup_restore_target_configured=_flag("RECPRO_BACKUP_RESTORE_TARGET_CONFIGURED"),
        model_policy=os.environ.get("RECPRO_PRODUCTION_MODEL_POLICY", "").strip(),
    )


def build_report(context: ProductionGateContext) -> dict[str, object]:
    report = evaluate_production_gate(context)
    return {
        "schema_version": "production-compose-preflight-v1",
        "policy_version": report.policy_version,
        "ready": report.ready,
        "checks": dict(report.checks),
        "missing": list(report.missing),
        "side_effects": {
            "database_reads": 0,
            "database_writes": 0,
            "neo4j_writes": 0,
            "chroma_writes": 0,
            "deepseek_requests": 0,
            "container_changes": 0,
            "volume_changes": 0,
            "deletions": 0,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="exclusive JSON report path")
    parser.add_argument(
        "--allow-not-ready",
        action="store_true",
        help="return success while reporting missing requirements",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = build_report(build_context())
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        write_json_exclusive(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["ready"] or args.allow_not_ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
