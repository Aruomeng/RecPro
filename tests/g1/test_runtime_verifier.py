from __future__ import annotations

import contextlib
import io
import unittest
from unittest.mock import patch

from scripts.verify_g1_runtime import (
    EXPECTED_SERVICES,
    build_parser,
    inspect_frontend_page,
    parse_probe_counts,
    parse_frontend_entrypoint,
    sanitized_failure_reason,
    stable_health_signature,
    validate_git_evidence_state,
    validate_health_pair,
    validate_run_id,
    validate_service_states,
    validated_port,
)


class RuntimeVerifierContractTests(unittest.TestCase):
    def test_accepts_truthful_g1_health_pair(self) -> None:
        validate_health_pair(
            200,
            {"status": "UP"},
            200,
            {
                "status": "DEGRADED",
                "can_recommend": False,
                "components": {
                    "mysql": {
                        "status": "UP",
                        "required": True,
                        "active_version": "libramas-g1-test-instance",
                    }
                },
            },
            "libramas-g1-test-instance",
        )

    def test_rejects_recommendation_capability_claim(self) -> None:
        with self.assertRaisesRegex(ValueError, "can_recommend=false"):
            validate_health_pair(
                200,
                {"status": "UP"},
                200,
                {
                    "status": "DEGRADED",
                    "can_recommend": True,
                    "components": {"mysql": {"status": "UP", "required": True}},
                },
            )

    def test_run_id_is_strict_and_append_only_friendly(self) -> None:
        self.assertEqual(validate_run_id("g1_20260802_001"), "g1_20260802_001")
        for invalid in ("..", "contains space", "/absolute", "a/b"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    validate_run_id(invalid)

    def test_all_five_services_must_be_running_without_restarts(self) -> None:
        states = {
            name: {
                "status": "running",
                "health": "healthy",
                "restart_count": 0,
            }
            for name in EXPECTED_SERVICES
        }
        validate_service_states(states)

        for service_name, field, unsafe_value in (
            ("worker", "status", "exited"),
            ("frontend", "health", "unhealthy"),
            ("neo4j", "restart_count", 1),
        ):
            with self.subTest(service=service_name, field=field):
                invalid = {name: dict(state) for name, state in states.items()}
                invalid[service_name][field] = unsafe_value
                with self.assertRaises(ValueError):
                    validate_service_states(invalid)

    def test_slow_clean_initialization_can_use_bounded_ten_minute_deadline(self) -> None:
        args = build_parser().parse_args(
            ["--run-id", "g1-slow-init", "--deadline-seconds", "600"]
        )
        self.assertEqual(600, args.deadline_seconds)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            build_parser().parse_args(
                ["--run-id", "g1-too-slow", "--deadline-seconds", "601"]
            )

    def test_health_comparison_ignores_only_observation_time(self) -> None:
        first = {"status": "UP", "time": "first", "service": "recpro-backend"}
        second = {"status": "UP", "time": "second", "service": "recpro-backend"}
        self.assertEqual(stable_health_signature(first), stable_health_signature(second))
        second["status"] = "DOWN"
        self.assertNotEqual(stable_health_signature(first), stable_health_signature(second))

    def test_runtime_urls_can_only_come_from_explicit_validated_ports(self) -> None:
        self.assertEqual(18000, validated_port({"PORT": "18000"}, "PORT"))
        for value in ("", "zero", "0", "65536"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validated_port({"PORT": value}, "PORT")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            build_parser().parse_args(
                ["--run-id", "g1-test", "--api-base-url", "http://example.test"]
            )

    def test_probe_counts_are_actual_and_exact(self) -> None:
        self.assertEqual(
            {"total_rows": 1, "matching_probe_rows": 1},
            parse_probe_counts("1\n1\n"),
        )
        for output in ("", "1\n", "2\n1\n", "1\n0\n", "one\n1\n"):
            with self.subTest(output=output), self.assertRaises(ValueError):
                parse_probe_counts(output)

    def test_runtime_evidence_requires_one_clean_git_commit(self) -> None:
        commit = "a" * 40
        self.assertEqual(commit, validate_git_evidence_state("", f"{commit}\n"))
        for status, observed_commit in (
            (" M backend/app/main.py\n", commit),
            ("", "HEAD"),
            ("", "A" * 40),
        ):
            with self.subTest(status=status, commit=observed_commit):
                with self.assertRaises(ValueError):
                    validate_git_evidence_state(status, observed_commit)

    def test_frontend_entrypoint_requires_local_production_assets(self) -> None:
        html = """
        <html><head><title>LibraMAS · 系统状态</title>
        <link rel="stylesheet" href="/assets/app-123.css"></head>
        <body><div id="app"></div><script src="/assets/app-123.js"></script></body></html>
        """
        self.assertEqual(
            ("/assets/app-123.css", "/assets/app-123.js"),
            parse_frontend_entrypoint(html),
        )
        for invalid in (
            html.replace('id="app"', 'id="missing"'),
            html.replace("/assets/app-123.js", "https://example.test/app.js"),
            html.replace("/assets/app-123.css", "/assets/../outside.css"),
        ):
            with self.subTest(html=invalid), self.assertRaises(ValueError):
                parse_frontend_entrypoint(invalid)

    def test_frontend_asset_html_fallback_is_rejected_by_content_type(self) -> None:
        html = (
            "<title>LibraMAS · 系统状态</title><div id=\"app\"></div>"
            "<link rel=\"stylesheet\" href=\"/assets/app.css\">"
            "<script src=\"/assets/app.js\"></script>"
        )
        with patch(
            "scripts.verify_g1_runtime.fetch_text", return_value=(200, html)
        ), patch(
            "scripts.verify_g1_runtime.fetch_bytes",
            return_value=(200, b"<!doctype html>", "text/html"),
        ), self.assertRaisesRegex(ValueError, "content type"):
            inspect_frontend_page("http://127.0.0.1:15173")

    def test_failure_reason_is_bounded_and_redacts_common_secrets(self) -> None:
        reason = sanitized_failure_reason(
            ValueError(
                f"{__file__} password=private-value "
                "https://runtime:private-value@127.0.0.1/failure"
            )
        )
        self.assertNotIn("private-value", reason)
        self.assertLessEqual(len(reason), 500)


if __name__ == "__main__":
    unittest.main()
