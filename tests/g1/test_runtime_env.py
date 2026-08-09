from __future__ import annotations

import unittest

from scripts.validate_runtime_env import EXAMPLE_PROJECT_NAME, validate_compose


def valid_values() -> dict[str, str]:
    return {
        "COMPOSE_PROJECT_NAME": "libramas-g1-researcher42-instance07",
        "RECPRO_CONFIG_BUNDLE_VERSION": "rec-1.0.0",
        "RECPRO_CONFIG_BUNDLE_PATH": "contracts/config/examples/rec-1.0.0.json",
        "RECPRO_CONFIG_BUNDLE_SHA256": (
            "220b0fb30f38fef7ca148c43b1f2751715c7df7ecf7d47e7ddfce7ff2847a5c6"
        ),
        "RECPRO_MYSQL_DATABASE": "recpro",
        "RECPRO_MYSQL_USER": "recpro_runtime",
        "RECPRO_MYSQL_PASSWORD": "runtime-secret-001",
        "RECPRO_MYSQL_MIGRATION_USER": "recpro_migrator",
        "RECPRO_MYSQL_MIGRATION_PASSWORD": "migration-secret-004",
        "RECPRO_PERSISTENCE_PROBE_ID": "libramas-g1-researcher42-instance07",
        "RECPRO_MYSQL_ROOT_PASSWORD": "bootstrap-secret-002",
        "RECPRO_MYSQL_HOST": "mysql",
        "RECPRO_MYSQL_PORT": "3306",
        "RECPRO_MYSQL_HOST_PORT": "13306",
        "RECPRO_NEO4J_HTTP_HOST_PORT": "17474",
        "RECPRO_NEO4J_BOLT_HOST_PORT": "17687",
        "RECPRO_BACKEND_HOST_PORT": "18000",
        "RECPRO_FRONTEND_HOST_PORT": "15173",
        "RECPRO_MYSQL_CONNECT_TIMEOUT_SECONDS": "3",
        "RECPRO_NEO4J_USER": "neo4j",
        "RECPRO_NEO4J_PASSWORD": "graph-secret-003",
    }


class RuntimeEnvironmentContractTests(unittest.TestCase):
    def test_distinct_isolated_compose_environment_passes(self) -> None:
        self.assertEqual((), validate_compose(valid_values()))

    def test_checked_in_project_placeholder_is_rejected(self) -> None:
        values = valid_values()
        values["COMPOSE_PROJECT_NAME"] = EXAMPLE_PROJECT_NAME
        self.assertIn(
            "COMPOSE_PROJECT_NAME still uses the checked-in placeholder",
            validate_compose(values),
        )

    def test_empty_or_reused_secrets_fail_closed(self) -> None:
        values = valid_values()
        values["RECPRO_MYSQL_ROOT_PASSWORD"] = ""
        values["RECPRO_NEO4J_PASSWORD"] = values["RECPRO_MYSQL_PASSWORD"]
        issues = validate_compose(values)
        self.assertIn("required value is empty: RECPRO_MYSQL_ROOT_PASSWORD", issues)
        self.assertIn(
            "runtime, bootstrap, and Neo4j secrets must be distinct",
            issues,
        )

    def test_bundle_path_cannot_escape_repository(self) -> None:
        values = valid_values()
        values["RECPRO_CONFIG_BUNDLE_PATH"] = "../outside.json"
        self.assertIn(
            "RECPRO_CONFIG_BUNDLE_PATH must stay inside the repository",
            validate_compose(values),
        )

    def test_probe_identity_must_equal_the_isolated_project(self) -> None:
        values = valid_values()
        values["RECPRO_PERSISTENCE_PROBE_ID"] = "another-g1-instance"
        self.assertIn(
            "RECPRO_PERSISTENCE_PROBE_ID must equal COMPOSE_PROJECT_NAME",
            validate_compose(values),
        )

    def test_neo4j_identity_matches_the_pinned_community_image(self) -> None:
        values = valid_values()
        values["RECPRO_NEO4J_USER"] = "another_user"
        self.assertIn(
            "RECPRO_NEO4J_USER must be neo4j for the pinned Community image",
            validate_compose(values),
        )

    def test_mysql_user_length_and_runtime_ranges_are_aligned(self) -> None:
        values = valid_values()
        values["RECPRO_MYSQL_USER"] = "u" * 33
        values["RECPRO_MYSQL_PORT"] = "70000"
        values["RECPRO_MYSQL_CONNECT_TIMEOUT_SECONDS"] = "0"
        issues = validate_compose(values)
        self.assertIn("RECPRO_MYSQL_USER has an unsafe identifier format", issues)
        self.assertIn("RECPRO_MYSQL_PORT must be between 1 and 65535", issues)
        self.assertIn(
            "RECPRO_MYSQL_CONNECT_TIMEOUT_SECONDS must be greater than 0 and at most 30",
            issues,
        )


if __name__ == "__main__":
    unittest.main()
