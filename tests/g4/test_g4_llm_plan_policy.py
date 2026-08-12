from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from scripts.execute_g4_recommendation_projection import (
    DEEPSEEK_PLAN_INTENT,
    DEEPSEEK_PRECONDITIONS,
    plan_enables_deepseek_intent,
)
from scripts.g4_llm_plan_policy import (
    EXPECTED_MODEL,
    load_deepseek_intent_policy,
    policy_hash,
)


class G4LLMPlanPolicyTests(unittest.TestCase):
    def test_policy_is_deepseek_intent_only_and_contains_no_secret(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env.test"
            env_file.write_text(
                "\n".join(
                    (
                        "RECPRO_APP_ENV=demo",
                        "RECPRO_MYSQL_PASSWORD=isolated-test-password",
                        "RECPRO_G4_HTTP_ENABLED=true",
                        "RECPRO_G4_LLM_INTENT_ENABLED=true",
                        "RECPRO_LLM_PROVIDER=deepseek",
                        "RECPRO_LLM_MODEL=deepseek-v4-flash",
                        "RECPRO_LLM_BASE_URL=https://api.deepseek.com",
                        "RECPRO_LLM_API_KEY=local-test-deepseek-key-001",
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            _settings, policy = load_deepseek_intent_policy(env_file)

        self.assertEqual(EXPECTED_MODEL, policy["model"])
        self.assertEqual("intent.classify", policy["capability"])
        self.assertFalse(policy["explanation_llm_enabled"])
        self.assertNotIn("key", " ".join(policy).lower())
        self.assertEqual(64, len(policy_hash(policy)))

    def test_executor_recognizes_only_a_policy_bound_plan(self) -> None:
        plan = {
            "intent": DEEPSEEK_PLAN_INTENT,
            "input_hashes": {"deepseek_intent_policy": "a" * 64},
            "preconditions": sorted(DEEPSEEK_PRECONDITIONS),
        }
        self.assertTrue(plan_enables_deepseek_intent(plan))
        self.assertFalse(plan_enables_deepseek_intent({"input_hashes": {}}))


if __name__ == "__main__":
    unittest.main()
