from __future__ import annotations

import unittest

from pydantic import ValidationError

from backend.app.config import AppSettings


class BackgroundPlanningConfigurationTests(unittest.TestCase):
    def _base(self) -> dict[str, object]:
        return {
            "app_env": "demo",
            "mysql_password": "isolated-test-password",
            "llm_provider": "deepseek",
            "llm_api_key": "local-test-deepseek-key-001",
        }

    def test_deepseek_planner_requires_complete_approved_identity(self) -> None:
        with self.assertRaisesRegex(ValidationError, "approved plan id"):
            AppSettings(
                **self._base(),
                background_planning_enabled=True,
                background_planning_provider="deepseek",
            )

    def test_deepseek_planner_accepts_only_demo_flash_with_identity(self) -> None:
        settings = AppSettings(
            **self._base(),
            background_planning_enabled=True,
            background_planning_provider="deepseek",
            background_planning_plan_id="468c40f8-5df9-56ba-b5ff-c5039aeaf23c",
            background_planning_plan_hash=("9a23203b7efbd51baa1d43d00fd68d35"
                                           "68c47b1eed1450d12d85f1a530552a32"),
            background_planning_run_identity="stage5-background-runtime-001",
        )
        self.assertEqual("deepseek", settings.background_planning_provider)

    def test_fixture_rejects_model_approval_identity(self) -> None:
        with self.assertRaisesRegex(ValidationError, "fixture background planning"):
            AppSettings(
                app_env="demo",
                mysql_password="isolated-test-password",
                background_planning_enabled=True,
                background_planning_provider="fixture",
                background_planning_plan_id="468c40f8-5df9-56ba-b5ff-c5039aeaf23c",
            )


if __name__ == "__main__":
    unittest.main()
