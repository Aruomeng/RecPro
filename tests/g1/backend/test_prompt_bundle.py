from __future__ import annotations

import unittest

from backend.app.config import DEFAULT_PROMPT_BUNDLE_SHA256
from backend.app.llm.prompts import (
    PromptBundleError,
    load_default_prompt_bundle,
    load_prompt_bundle,
)


class PromptBundleTest(unittest.TestCase):
    def test_default_bundle_is_versioned_and_has_no_tools(self) -> None:
        bundle = load_prompt_bundle(
            expected_sha256=DEFAULT_PROMPT_BUNDLE_SHA256,
            expected_version="prompt-v1",
        )
        self.assertEqual("prompt-bundle-v1", bundle.schema_version)
        self.assertEqual("prompt-v1", bundle.bundle_version)
        self.assertEqual(
            {
                "intent.classify",
                "feedback.parse",
                "explanation.render",
                "group_summary.render",
            },
            set(bundle.tasks),
        )
        self.assertTrue(all(task.evidence_only for task in bundle.tasks.values() if task.prompt_id.endswith("render")))

    def test_rendering_is_allowlisted_and_deterministic(self) -> None:
        bundle = load_default_prompt_bundle()
        values = {
            "allowed_intents": ["BOOK_RECOMMENDATION"],
            "input_text": "请推荐多智能体图书",
            "resource_types": ["BOOK"],
        }
        first = bundle.render("intent.classify", values)
        second = bundle.render("intent.classify", values)
        self.assertEqual(first, second)
        self.assertIn("多智能体图书", first.user)
        self.assertIn("<user_input>", first.user)
        self.assertEqual(64, len(first.template_sha256))

    def test_missing_extra_and_oversized_variables_fail_closed(self) -> None:
        bundle = load_default_prompt_bundle()
        with self.assertRaises(PromptBundleError):
            bundle.render("intent.classify", {"input_text": "x", "resource_types": []})
        with self.assertRaises(PromptBundleError):
            bundle.render(
                "intent.classify",
                {
                    "allowed_intents": [],
                    "input_text": "x",
                    "resource_types": [],
                    "unexpected": "not allowed",
                },
            )
        with self.assertRaises(PromptBundleError):
            bundle.render(
                "intent.classify",
                {
                    "allowed_intents": [],
                    "input_text": "x" * 5000,
                    "resource_types": [],
                },
            )

    def test_output_schema_rejects_unknown_or_invalid_fields(self) -> None:
        task = load_default_prompt_bundle().task("intent.classify")
        with self.assertRaises(PromptBundleError):
            task.validate_output({"intent": "UNSAFE"})
        with self.assertRaises(PromptBundleError):
            task.validate_output({"intent": "BOOK_RECOMMENDATION", "resource_id": 1})

    def test_hash_mismatch_is_rejected(self) -> None:
        with self.assertRaises(PromptBundleError):
            load_prompt_bundle(expected_sha256="0" * 64)


if __name__ == "__main__":
    unittest.main()
