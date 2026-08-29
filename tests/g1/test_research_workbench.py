from __future__ import annotations

import unittest

from scripts.run_research_workbench import merge_runtime_values, validate_configuration


class ResearchWorkbenchTests(unittest.TestCase):
    def valid_values(self) -> dict[str, str]:
        return {
            "RECPRO_APP_ENV": "demo",
            "RECPRO_G4_HTTP_ENABLED": "true",
            "RECPRO_G5_INTERACTION_HTTP_ENABLED": "true",
            "RECPRO_G4_LLM_INTENT_ENABLED": "true",
            "RECPRO_G4_LLM_EXPLANATION_ENABLED": "true",
            "RECPRO_LLM_PROVIDER": "deepseek",
            "RECPRO_LLM_MODEL": "deepseek-v4-flash",
            "RECPRO_LLM_API_KEY": "secret-present",
            "RECPRO_MYSQL_HOST": "127.0.0.1",
            "RECPRO_MYSQL_PORT": "62306",
            "RECPRO_LIBRARY_NEO4J_HTTP_HOST_PORT": "62475",
            "RECPRO_NEO4J_READ_USER": "recpro_graph_reader",
            "RECPRO_NEO4J_READ_PASSWORD": "secret-present",
        }

    def test_complete_research_configuration_is_accepted(self) -> None:
        self.assertEqual((), validate_configuration(self.valid_values()))

    def test_every_capability_is_fail_closed(self) -> None:
        for name in (
            "RECPRO_G4_HTTP_ENABLED",
            "RECPRO_G5_INTERACTION_HTTP_ENABLED",
            "RECPRO_G4_LLM_INTENT_ENABLED",
            "RECPRO_G4_LLM_EXPLANATION_ENABLED",
        ):
            values = self.valid_values()
            values[name] = "false"
            with self.subTest(name=name):
                self.assertTrue(validate_configuration(values))

    def test_mock_or_wrong_model_is_rejected(self) -> None:
        values = self.valid_values()
        values["RECPRO_LLM_PROVIDER"] = "mock"
        values["RECPRO_LLM_MODEL"] = "deepseek-chat"
        issues = validate_configuration(values)
        self.assertEqual(2, len(issues))

    def test_admin_credentials_do_not_satisfy_runtime_read_identity(self) -> None:
        values = self.valid_values()
        values.pop("RECPRO_NEO4J_READ_USER")
        values.pop("RECPRO_NEO4J_READ_PASSWORD")
        values["RECPRO_NEO4J_ADMIN_USER"] = "neo4j"
        values["RECPRO_NEO4J_ADMIN_PASSWORD"] = "operator-secret"

        issues = validate_configuration(values)

        self.assertIn("RECPRO_NEO4J_READ_USER must be configured", issues)
        self.assertIn("RECPRO_NEO4J_READ_PASSWORD must be configured", issues)

    def test_final_graph_secrets_override_only_runtime_graph_identity(self) -> None:
        values = merge_runtime_values(
            {"RECPRO_LLM_API_KEY": "llm-secret"},
            {
                "RECPRO_NEO4J_ADMIN_USER": "source-admin",
                "RECPRO_NEO4J_ADMIN_PASSWORD": "source-secret",
                "RECPRO_LIBRARY_NEO4J_HTTP_HOST_PORT": "62475",
            },
            {
                "RECPRO_FINAL_NEO4J_PROJECT_NAME": "final-project",
                "RECPRO_FINAL_NEO4J_HTTP_HOST_PORT": "62948",
                "RECPRO_FINAL_NEO4J_BOLT_HOST_PORT": "62968",
                "RECPRO_FINAL_NEO4J_PASSWORD": "final-secret",
            },
        )

        self.assertEqual("62948", values["RECPRO_LIBRARY_NEO4J_HTTP_HOST_PORT"])
        self.assertEqual("neo4j", values["RECPRO_NEO4J_READ_USER"])
        self.assertEqual("final-secret", values["RECPRO_NEO4J_READ_PASSWORD"])
        self.assertEqual("source-admin", values["RECPRO_NEO4J_ADMIN_USER"])
        self.assertEqual("source-secret", values["RECPRO_NEO4J_ADMIN_PASSWORD"])

    def test_incomplete_final_graph_secret_bundle_is_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "incomplete"):
            merge_runtime_values({}, {}, {"RECPRO_FINAL_NEO4J_PASSWORD": "present"})


if __name__ == "__main__":
    unittest.main()
