from __future__ import annotations

import unittest

from backend.app.agent_workspace.adapters.deepseek_planner import DeepSeekBackgroundPlanner
from backend.app.agent_workspace.ports.planning import SanitizedPlanningContext
from backend.app.llm.ports.public import LLMResult
from backend.app.llm.prompts import load_prompt_bundle


class _FakeModel:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.contexts: list[str] = []

    async def plan_workspace_background(self, context_json: str) -> LLMResult:
        self.contexts.append(context_json)
        return LLMResult(
            provider="deepseek",
            model="deepseek-v4-flash",
            prompt_version="background-planning-prompt-v1",
            prompt_id="workspace.background_plan",
            payload=self.payload if isinstance(self.payload, dict) else {},
        )


class DeepSeekBackgroundPlannerTests(unittest.IsolatedAsyncioTestCase):
    def _context(self) -> SanitizedPlanningContext:
        return SanitizedPlanningContext(
            mode="guest",
            context_version=1,
            trigger="SESSION_STARTED",
            route="/",
            query="推荐系统",
            top_topics=("推荐系统",),
            source_statuses={"mysql": "UP"},
            external_context=(),
        )

    def test_dedicated_prompt_bundle_is_local_and_tool_free(self) -> None:
        bundle = load_prompt_bundle(
            "contracts/prompts/background-planning-prompts-v1.json",
            expected_version="prompt-v3",
        )
        task = bundle.task("workspace.background_plan")
        self.assertEqual({"workspace.background_plan"}, set(bundle.tasks))
        self.assertEqual("RecommendationPolicyAgent", task.agent_name)
        self.assertEqual(("context_json",), task.variables)
        self.assertEqual(3, task.output_schema["properties"]["suggested_topics"]["maxItems"])

    async def test_adapter_passes_only_serialized_sanitized_context(self) -> None:
        model = _FakeModel({"suggested_topics": ["推荐系统", "智慧图书馆"]})
        result = await DeepSeekBackgroundPlanner(model).plan(self._context())
        self.assertEqual(1, result.model_requests)
        self.assertEqual("deepseek", result.provider)
        self.assertEqual("SUGGEST_TOPICS", result.directives[0]["directive_type"])
        self.assertEqual(["推荐系统", "智慧图书馆"], result.directives[0]["payload"]["topics"])
        self.assertEqual("BACKGROUND_MODEL_TOPICS", result.directives[0]["reason_code"])
        self.assertNotIn("user_id", model.contexts[0])
        self.assertNotIn("token", model.contexts[0])

    async def test_adapter_rejects_invalid_topic_payload(self) -> None:
        model = _FakeModel({"suggested_topics": ["safe", 1]})
        with self.assertRaisesRegex(ValueError, "invalid topic"):
            await DeepSeekBackgroundPlanner(model).plan(self._context())


if __name__ == "__main__":
    unittest.main()
