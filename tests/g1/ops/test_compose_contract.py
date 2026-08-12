from __future__ import annotations

import re
import unittest
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[3]
COMPOSE_PATH = ROOT / "compose.yaml"
COMPOSE_ENV_PATH = ROOT / ".env.compose.example"
HOST_ENV_PATH = ROOT / ".env.host.example"
MYSQL_INIT_PATH = ROOT / "infra/mysql/init/10-create-runtime-user.sh"


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator:
            raise AssertionError(f"invalid environment line in {path}: {raw_line}")
        values[key] = value
    return values


class ComposeContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.compose_text = COMPOSE_PATH.read_text(encoding="utf-8")
        cls.compose: dict[str, Any] = yaml.load(
            cls.compose_text,
            Loader=yaml.BaseLoader,
        )
        cls.services = cls.compose["services"]
        cls.compose_env = load_env(COMPOSE_ENV_PATH)
        cls.host_env = load_env(HOST_ENV_PATH)
        cls.mysql_init = MYSQL_INIT_PATH.read_text(encoding="utf-8")

    def test_project_and_service_names_are_explicit(self) -> None:
        self.assertIn("${COMPOSE_PROJECT_NAME:?", self.compose["name"])
        self.assertEqual(
            {"mysql", "neo4j", "backend", "worker", "frontend"},
            set(self.services),
        )
        self.assertRegex(
            self.compose_env["COMPOSE_PROJECT_NAME"],
            re.compile(r"^[a-z0-9][a-z0-9_-]+$"),
        )

    def test_infrastructure_images_are_exact_non_floating_tags(self) -> None:
        expected_tags = {
            "mysql": "mysql:8.4.10",
            "neo4j": "neo4j:5.26.28-community",
        }
        for service_name, expected_tag in expected_tags.items():
            image = self.services[service_name]["image"]
            self.assertTrue(image.startswith(expected_tag + "@sha256:"))
            self.assertNotIn(":" + "latest", image.lower())
            self.assertRegex(image, re.compile(r"@sha256:[0-9a-f]{64}$"))

    def test_named_data_volumes_are_unique_and_persistent(self) -> None:
        volumes = self.compose["volumes"]
        self.assertEqual(
            "${COMPOSE_PROJECT_NAME}_mysql_data",
            volumes["mysql_data"]["name"],
        )
        self.assertEqual(
            "${COMPOSE_PROJECT_NAME}_neo4j_data",
            volumes["neo4j_data"]["name"],
        )
        self.assertEqual(
            "${COMPOSE_PROJECT_NAME}_chroma_data",
            volumes["chroma_data"]["name"],
        )
        self.assertIn("mysql_data:/var/lib/mysql", self.services["mysql"]["volumes"])
        self.assertIn("neo4j_data:/data", self.services["neo4j"]["volumes"])
        for service_name in ("backend", "worker"):
            self.assertIn(
                "chroma_data:/srv/recpro/data/chroma",
                self.services[service_name]["volumes"],
            )

    def test_host_ports_are_bound_to_loopback(self) -> None:
        for service_name in ("mysql", "neo4j", "backend", "frontend"):
            for port in self.services[service_name].get("ports", []):
                self.assertTrue(
                    port.startswith("127.0.0.1:"),
                    f"{service_name} port is not loopback-only: {port}",
                )

    def test_health_dependencies_are_fail_closed(self) -> None:
        self.assertIn("healthcheck", self.services["mysql"])
        self.assertIn("healthcheck", self.services["neo4j"])
        self.assertIn("healthcheck", self.services["backend"])
        self.assertIn("healthcheck", self.services["worker"])
        self.assertIn("healthcheck", self.services["frontend"])
        for service_name in ("backend", "worker"):
            self.assertEqual(
                "service_healthy",
                self.services[service_name]["depends_on"]["mysql"]["condition"],
            )
        self.assertEqual(
            "service_healthy",
            self.services["frontend"]["depends_on"]["backend"]["condition"],
        )
        self.assertNotIn("neo4j", self.services["backend"]["depends_on"])
        self.assertIn(
            "/api/v1/health/live",
            " ".join(self.services["backend"]["healthcheck"]["test"]),
        )
        self.assertIn(
            "/healthz",
            " ".join(self.services["frontend"]["healthcheck"]["test"]),
        )
        worker_healthcheck = " ".join(
            self.services["worker"]["healthcheck"]["test"]
        )
        self.assertIn("backend.app.worker", worker_healthcheck)
        self.assertNotIn("/api/v1/health/live", worker_healthcheck)

    def test_application_build_and_commands_match_runtime_contract(self) -> None:
        for service_name in ("backend", "worker"):
            self.assertEqual(".", self.services[service_name]["build"]["context"])
            self.assertEqual(
                "backend/Dockerfile",
                self.services[service_name]["build"]["dockerfile"],
            )
        self.assertEqual(
            [
                "python",
                "-m",
                "uvicorn",
                "backend.app.main:app",
                "--host",
                "0.0.0.0",
                "--port",
                "8000",
            ],
            self.services["backend"]["command"],
        )
        self.assertEqual("./frontend", self.services["frontend"]["build"]["context"])
        self.assertEqual("Dockerfile", self.services["frontend"]["build"]["dockerfile"])

    def test_backend_and_worker_receive_only_runtime_mysql_identity(self) -> None:
        for service_name in ("backend", "worker"):
            environment = self.services[service_name]["environment"]
            self.assertEqual("mysql", environment["RECPRO_MYSQL_HOST"])
            self.assertIn("RECPRO_MYSQL_PASSWORD", environment)
            self.assertIn("RECPRO_LLM_PROVIDER", environment)
            self.assertIn("RECPRO_G4_LLM_INTENT_ENABLED", environment)
            self.assertIn("RECPRO_LLM_API_KEY", environment)
            self.assertIn("RECPRO_PROMPT_BUNDLE_SHA256", environment)
            self.assertNotIn("MYSQL_ROOT_PASSWORD", environment)
            self.assertNotIn("RECPRO_MYSQL_ROOT_PASSWORD", environment)
        self.assertEqual(
            ["python", "-m", "backend.app.worker"],
            self.services["worker"]["command"],
        )
        mysql_environment = self.services["mysql"]["environment"]
        self.assertNotIn("MYSQL_USER", mysql_environment)
        self.assertNotIn("MYSQL_PASSWORD", mysql_environment)
        mysql_healthcheck = " ".join(self.services["mysql"]["healthcheck"]["test"])
        self.assertIn("RECPRO_MYSQL_RUNTIME_USER", mysql_healthcheck)
        self.assertNotIn("--user=root", mysql_healthcheck)

    def test_host_and_compose_examples_use_distinct_database_hosts(self) -> None:
        self.assertEqual("127.0.0.1", self.host_env["RECPRO_MYSQL_HOST"])
        self.assertEqual("mysql", self.compose_env["RECPRO_MYSQL_HOST"])
        for values in (self.host_env, self.compose_env):
            self.assertEqual("recpro_runtime", values["RECPRO_MYSQL_USER"])
            self.assertEqual("", values["RECPRO_MYSQL_PASSWORD"])
            self.assertEqual("recpro_migrator", values["RECPRO_MYSQL_MIGRATION_USER"])
            self.assertEqual("", values["RECPRO_MYSQL_MIGRATION_PASSWORD"])
        self.assertEqual("", self.compose_env["RECPRO_MYSQL_ROOT_PASSWORD"])
        self.assertEqual("", self.compose_env["RECPRO_NEO4J_PASSWORD"])

    def test_config_bundle_identity_is_explicit_and_shared(self) -> None:
        expected_hash = "220b0fb30f38fef7ca148c43b1f2751715c7df7ecf7d47e7ddfce7ff2847a5c6"
        for values in (self.host_env, self.compose_env):
            self.assertEqual("rec-1.0.0", values["RECPRO_CONFIG_BUNDLE_VERSION"])
            self.assertEqual(
                "contracts/config/examples/rec-1.0.0.json",
                values["RECPRO_CONFIG_BUNDLE_PATH"],
            )
            self.assertEqual(expected_hash, values["RECPRO_CONFIG_BUNDLE_SHA256"])

    def test_persistence_probe_is_bound_to_the_isolated_project(self) -> None:
        expected_project = self.compose_env["COMPOSE_PROJECT_NAME"]
        self.assertEqual(
            expected_project,
            self.compose_env["RECPRO_PERSISTENCE_PROBE_ID"],
        )
        self.assertEqual(
            expected_project,
            self.host_env["RECPRO_PERSISTENCE_PROBE_ID"],
        )
        for service_name in ("backend", "worker"):
            self.assertIn(
                "COMPOSE_PROJECT_NAME",
                self.services[service_name]["environment"][
                    "RECPRO_PERSISTENCE_PROBE_ID"
                ],
            )
        self.assertIn(
            "COMPOSE_PROJECT_NAME",
            self.services["mysql"]["environment"]["RECPRO_PERSISTENCE_PROBE_ID"],
        )

    def test_mysql_new_volume_hook_grants_only_append_permissions(self) -> None:
        self.assertIn("CREATE TABLE IF NOT EXISTS", self.mysql_init)
        self.assertIn("recpro_runtime_probe", self.mysql_init)
        self.assertIn("INSERT IGNORE INTO", self.mysql_init)
        self.assertIn("RECPRO_PERSISTENCE_PROBE_ID", self.mysql_init)
        self.assertIn("VALUES ('${probe_id}')", self.mysql_init)
        self.assertIn("CREATE USER IF NOT EXISTS", self.mysql_init)
        self.assertIn("GRANT SELECT, INSERT ON", self.mysql_init)
        self.assertIn(
            "GRANT SELECT, INSERT, UPDATE, CREATE, REFERENCES, INDEX ON",
            self.mysql_init,
        )
        self.assertNotIn("GRANT SELECT, INSERT, " + "UPDATE ON", self.mysql_init)
        forbidden_sql = (
            "DE" + "LETE",
            "DR" + "OP",
            "TRUN" + "CATE",
            "ALTER",
        )
        upper_script = self.mysql_init.upper()
        for token in forbidden_sql:
            self.assertNotIn(token, upper_script)

    def test_executable_orchestration_has_no_cleanup_command(self) -> None:
        executable_text = self.compose_text + "\n" + self.mysql_init
        forbidden_commands = (
            "docker compose " + "down -v",
            "docker compose " + "down --volumes",
            "docker compose " + "rm",
            "docker volume " + "rm",
            "docker volume " + "prune",
            "docker system " + "prune",
            "docker image " + "prune",
        )
        for command in forbidden_commands:
            self.assertNotIn(command, executable_text.lower())


if __name__ == "__main__":
    unittest.main()
