from __future__ import annotations

import unittest

from scripts.run_research_workbench import validate_configuration


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
            "RECPRO_NEO4J_ADMIN_USER": "neo4j",
            "RECPRO_NEO4J_ADMIN_PASSWORD": "secret-present",
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


if __name__ == "__main__":
    unittest.main()
