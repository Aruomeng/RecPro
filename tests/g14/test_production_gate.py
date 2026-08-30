from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.app.platform.production import (
    ProductionGateContext,
    ProductionGateError,
    evaluate_production_gate,
    require_production_gate,
)
from scripts.verify_production_deployment import build_context, build_report


def _context(**overrides: object) -> ProductionGateContext:
    values: dict[str, object] = {
        "app_env": "production",
        "production_http_enabled": True,
        "auth_enabled": True,
        "auth_mode": "oidc",
        "oidc_issuer": "https://id.example.edu",
        "oidc_audience": "libramas-api",
        "oidc_jwks_uri": "https://id.example.edu/.well-known/jwks.json",
        "jwks_fetcher_configured": True,
        "oidc_identity_mapper_configured": True,
        "tls_termination_enabled": True,
        "secure_cookies": True,
        "runtime_database_user": "recpro_runtime",
        "graph_readonly_user": "recpro_graph_reader",
        "recommendation_api_enabled": True,
        "feedback_api_enabled": True,
        "behavior_api_enabled": True,
        "readiness_confirmed": True,
        "backup_restore_target_configured": True,
        "model_policy": "DETERMINISTIC_FALLBACK",
    }
    values.update(overrides)
    return ProductionGateContext(**values)  # type: ignore[arg-type]


class ProductionGateTests(unittest.TestCase):
    def test_complete_context_is_ready_without_side_effects(self) -> None:
        report = require_production_gate(_context())
        self.assertTrue(report.ready)
        self.assertEqual((), report.missing)
        self.assertTrue(all(report.checks.values()))

    def test_missing_oidc_or_tls_is_reported_as_a_bounded_failure(self) -> None:
        report = evaluate_production_gate(
            _context(oidc_identity_mapper_configured=False, tls_termination_enabled=False)
        )
        self.assertFalse(report.ready)
        self.assertEqual(
            ("oidc_identity_mapper", "tls_termination"),
            report.missing,
        )

    def test_local_or_hybrid_auth_cannot_be_used_by_deployment_profile(self) -> None:
        for mode in ("local", "hybrid"):
            with self.subTest(mode=mode):
                report = evaluate_production_gate(_context(auth_mode=mode))
                self.assertIn("oidc_only_auth_mode", report.missing)

    def test_admin_data_identities_and_insecure_urls_are_rejected(self) -> None:
        report = evaluate_production_gate(
            _context(
                runtime_database_user="root",
                graph_readonly_user="neo4j",
                oidc_jwks_uri="https://user:password@example.edu/jwks",
            )
        )
        self.assertFalse(report.ready)
        self.assertIn("least_privilege_mysql_runtime", report.missing)
        self.assertIn("least_privilege_graph_reader", report.missing)
        self.assertIn("oidc_jwks_uri", report.missing)

    def test_error_contains_only_public_requirement_names(self) -> None:
        with self.assertRaises(ProductionGateError) as caught:
            require_production_gate(
                _context(
                    app_env="demo",
                    runtime_database_user="root",
                    model_policy="not-a-policy",
                )
            )
        text = str(caught.exception)
        self.assertIn("production_environment", text)
        self.assertNotIn("password", text.lower())
        self.assertNotIn("secret", text.lower())

    def test_environment_preflight_is_read_only_and_does_not_echo_secrets(self) -> None:
        values = {
            "RECPRO_APP_ENV": "production",
            "RECPRO_PRODUCTION_HTTP_ENABLED": "true",
            "RECPRO_AUTH_ENABLED": "true",
            "RECPRO_AUTH_MODE": "oidc",
            "RECPRO_AUTH_COOKIE_SECURE": "true",
            "RECPRO_OIDC_ISSUER": "https://id.example.edu",
            "RECPRO_OIDC_AUDIENCE": "libramas-api",
            "RECPRO_OIDC_JWKS_URI": "https://id.example.edu/jwks",
            "RECPRO_OIDC_FETCHER_CONFIGURED": "true",
            "RECPRO_OIDC_MAPPER_CONFIGURED": "true",
            "RECPRO_TLS_TERMINATION_ENABLED": "true",
            "RECPRO_MYSQL_USER": "recpro_runtime",
            "RECPRO_NEO4J_READ_USER": "recpro_graph_reader",
            "RECPRO_RECOMMENDATION_API_ENABLED": "true",
            "RECPRO_FEEDBACK_API_ENABLED": "true",
            "RECPRO_BEHAVIOR_API_ENABLED": "true",
            "RECPRO_READINESS_CONFIRMED": "true",
            "RECPRO_BACKUP_RESTORE_TARGET_CONFIGURED": "true",
            "RECPRO_PRODUCTION_MODEL_POLICY": "DETERMINISTIC_FALLBACK",
            "RECPRO_MYSQL_PASSWORD": "do-not-print-this-value",
        }
        with patch.dict("os.environ", values, clear=False):
            report = build_report(build_context())
        self.assertTrue(report["ready"])
        self.assertEqual(0, report["side_effects"]["database_writes"])
        self.assertNotIn("do-not-print", str(report))


if __name__ == "__main__":
    unittest.main()
