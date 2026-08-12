from __future__ import annotations

import unittest

from scripts.sync_host_env_from_compose import (
    build_overrides,
    read_env_from_text,
    render_env,
)


class HostEnvSyncTests(unittest.TestCase):
    def compose_values(self) -> dict[str, str]:
        return {
            "COMPOSE_PROJECT_NAME": "recpro-isolated-20260811a",
            "RECPRO_MYSQL_HOST_PORT": "62306",
            "RECPRO_MYSQL_DATABASE": "recpro",
            "RECPRO_MYSQL_USER": "recpro_runtime",
            "RECPRO_MYSQL_PASSWORD": "runtime-secret-20260811",
            "RECPRO_MYSQL_MIGRATION_USER": "recpro_migrator",
            "RECPRO_MYSQL_MIGRATION_PASSWORD": "migration-secret-20260811",
            "RECPRO_MYSQL_CONNECT_TIMEOUT_SECONDS": "3",
            "RECPRO_LLM_PROVIDER": "deepseek",
            "RECPRO_LLM_BASE_URL": "https://api.deepseek.com",
            "RECPRO_LLM_MODEL": "deepseek-v4-flash",
            "RECPRO_LLM_API_KEY": "key-secret-20260811",
            "RECPRO_LLM_TIMEOUT_SECONDS": "20",
            "RECPRO_LLM_MAX_OUTPUT_TOKENS": "512",
            "RECPRO_PROMPT_BUNDLE_VERSION": "prompt-v1",
            "RECPRO_PROMPT_BUNDLE_PATH": "contracts/prompts/rec-prompts-v1.0.1.json",
            "RECPRO_PROMPT_BUNDLE_SHA256": "a" * 64,
        }

    def test_render_preserves_comments_and_adds_required_host_keys(self) -> None:
        overrides = build_overrides(self.compose_values())
        rendered, changed = render_env(
            "# keep this comment\nRECPRO_MYSQL_HOST=mysql\nRECPRO_MYSQL_PORT=3306\n",
            overrides,
        )
        values = read_env_from_text(rendered)
        self.assertEqual("127.0.0.1", values["RECPRO_MYSQL_HOST"])
        self.assertEqual("62306", values["RECPRO_MYSQL_PORT"])
        self.assertEqual("recpro-isolated-20260811a", values["RECPRO_PERSISTENCE_PROBE_ID"])
        self.assertEqual("recpro_migrator", values["RECPRO_MYSQL_MIGRATION_USER"])
        self.assertIn("# keep this comment", rendered)
        self.assertIn("RECPRO_DEMO_HTTP_ENABLED", changed)
        self.assertEqual("false", values["RECPRO_G5_INTERACTION_HTTP_ENABLED"])

    def test_render_does_not_remove_unrelated_existing_keys(self) -> None:
        overrides = build_overrides(self.compose_values())
        rendered, _ = render_env(
            "RECPRO_BACKEND_PORT=8000\nCUSTOM_LOCAL_NOTE=preserve-me\n",
            overrides,
        )
        values = read_env_from_text(rendered)
        self.assertEqual("8000", values["RECPRO_BACKEND_PORT"])
        self.assertEqual("preserve-me", values["CUSTOM_LOCAL_NOTE"])


if __name__ == "__main__":
    unittest.main()
