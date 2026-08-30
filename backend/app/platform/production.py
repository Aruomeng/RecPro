"""Fail-closed checks for the single-host production deployment profile.

The application composition functions deliberately remain injectable and
side-effect free.  This module is the small policy boundary used by a future
deployment entrypoint (and by its preflight command) to prove that the
production graph is not accidentally started with research credentials,
plain HTTP, or an unconfigured external identity provider.

It only evaluates immutable, public configuration facts.  It never opens a
socket, reads a secret value, starts a container, migrates a database, or
contacts an OIDC provider.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlsplit


_SAFE_RUNTIME_USERS = frozenset({"root", "neo4j", "admin", "administrator"})
_MODEL_POLICIES = frozenset({"APPROVED_EXTERNAL", "DETERMINISTIC_FALLBACK"})


class ProductionGateError(ValueError):
    """Raised when a deployment profile is not safe to compose."""

    def __init__(self, report: "ProductionGateReport") -> None:
        self.report = report
        details = ", ".join(report.missing)
        super().__init__(f"production deployment gate rejected: {details}")


@dataclass(frozen=True, slots=True)
class ProductionGateContext:
    """Non-secret evidence required by the production composition gate."""

    app_env: str
    production_http_enabled: bool
    auth_enabled: bool
    auth_mode: str
    oidc_issuer: str | None
    oidc_audience: str | None
    oidc_jwks_uri: str | None
    jwks_fetcher_configured: bool
    oidc_identity_mapper_configured: bool
    tls_termination_enabled: bool
    secure_cookies: bool
    runtime_database_user: str | None
    graph_readonly_user: str | None
    recommendation_api_enabled: bool
    feedback_api_enabled: bool
    behavior_api_enabled: bool
    readiness_confirmed: bool
    backup_restore_target_configured: bool
    model_policy: str


@dataclass(frozen=True, slots=True)
class ProductionGateReport:
    """Auditable result containing no credentials or raw provider data."""

    ready: bool
    checks: Mapping[str, bool]
    missing: tuple[str, ...]
    policy_version: str = "production-compose-gate-v1"


def evaluate_production_gate(context: ProductionGateContext) -> ProductionGateReport:
    """Evaluate all production requirements without performing side effects."""

    checks: dict[str, bool] = {
        "production_environment": context.app_env == "production",
        "production_http_switch": context.production_http_enabled,
        "formal_authentication": context.auth_enabled,
        # Local JWT remains a research mode.  Production requires an external
        # issuer; the hybrid mode is intentionally not accepted here.
        "oidc_only_auth_mode": context.auth_mode == "oidc",
        "oidc_issuer": _https_value(context.oidc_issuer),
        "oidc_audience": _non_blank(context.oidc_audience),
        "oidc_jwks_uri": _https_value(context.oidc_jwks_uri),
        "jwks_fetcher": context.jwks_fetcher_configured,
        "oidc_identity_mapper": context.oidc_identity_mapper_configured,
        "tls_termination": context.tls_termination_enabled,
        "secure_cookies": context.secure_cookies,
        "least_privilege_mysql_runtime": _least_privilege_user(
            context.runtime_database_user
        ),
        "least_privilege_graph_reader": _least_privilege_user(
            context.graph_readonly_user
        ),
        "recommendation_api": context.recommendation_api_enabled,
        "feedback_api": context.feedback_api_enabled,
        "behavior_api": context.behavior_api_enabled,
        "readiness_confirmed": context.readiness_confirmed,
        "backup_restore_target": context.backup_restore_target_configured,
        "model_policy": context.model_policy in _MODEL_POLICIES,
    }
    missing = tuple(name for name, passed in checks.items() if not passed)
    return ProductionGateReport(ready=not missing, checks=checks, missing=missing)


def require_production_gate(context: ProductionGateContext) -> ProductionGateReport:
    """Return a ready report or fail before a production app is composed."""

    report = evaluate_production_gate(context)
    if not report.ready:
        raise ProductionGateError(report)
    return report


def _non_blank(value: str | None) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _https_value(value: str | None) -> bool:
    if not _non_blank(value):
        return False
    parsed = urlsplit(value.strip())
    return (
        parsed.scheme.lower() == "https"
        and bool(parsed.netloc)
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
    )


def _least_privilege_user(value: str | None) -> bool:
    if not _non_blank(value):
        return False
    normalized = value.strip().lower()
    return normalized not in _SAFE_RUNTIME_USERS and len(normalized) <= 64


__all__ = [
    "ProductionGateContext",
    "ProductionGateError",
    "ProductionGateReport",
    "evaluate_production_gate",
    "require_production_gate",
]
