from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4
import unittest

from backend.app.agent_workspace import (
    AgentWorkspaceBroker,
    BackgroundPlanningCoordinator,
    DirectiveValidationError,
    DirectiveValidator,
    FixtureBackgroundPlanner,
    InMemoryPlanningBudget,
    PlanningBudgetPolicy,
    PlanningContextSanitizer,
)
from backend.app.agent_workspace.ports.handlers import WorkspaceDirectiveProposal
from backend.app.agent_workspace.ports.planning import PlanningContext
from backend.app.agent_workspace.ports.planning import SanitizedPlanningContext, BackgroundPlanningResult


class _FailingPlanner:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def plan(self, context: SanitizedPlanningContext) -> BackgroundPlanningResult:
        raise self.error


class _CapturingPlanner:
    def __init__(self) -> None:
        self.contexts: list[SanitizedPlanningContext] = []

    async def plan(self, context: SanitizedPlanningContext) -> BackgroundPlanningResult:
        self.contexts.append(context)
        return BackgroundPlanningResult(
            evidence_refs=("workspace:context",),
            confidence=0.8,
        )


class _ProfileReader:
    def __init__(self) -> None:
        self.calls: list[int] = []

    async def summary(self, user_id: int) -> dict[str, object]:
        self.calls.append(user_id)
        return {"major": "图书情报", "user_id": user_id, "profile_version": "v1"}


class BackgroundPlanningTests(unittest.IsolatedAsyncioTestCase):
    def _context(self, *, version: int = 2, trigger: str = "SESSION_STARTED", consent: bool = False) -> PlanningContext:
        return PlanningContext(
            workspace_id=uuid4(), session_id=uuid4(), device_id="kiosk-a",
            mode="authenticated" if consent else "guest", context_version=version,
            trigger=trigger, route="/", query="多智能体与智慧图书馆",
            top_topics=("推荐系统", "知识图谱"),
            source_statuses={"mysql": "UP", "neo4j": "UP", "chroma": "UNKNOWN"},
            external_context=({
                "source_id": "demo-calendar", "kind": "EXTERNAL_DEMO", "label": "演示日历",
                "status": "UP", "observed_at": "2026-08-30T00:00:00Z",
                "expires_at": "2026-08-30T00:05:00Z",
                "values": {"suggested_topics": ["多智能体"], "token": "should-not-pass"},
            },),
            personalization_enabled=consent,
            profile_summary={"major": "图书情报", "user_id": 10000} if consent else None,
        )

    async def test_fixture_planner_is_event_triggered_and_budgeted(self) -> None:
        now = datetime(2026, 8, 30, 0, 0, tzinfo=UTC)
        coordinator = BackgroundPlanningCoordinator(
            planner=FixtureBackgroundPlanner(),
            budget=InMemoryPlanningBudget(),
            clock=lambda: now,
        )
        dispatched: list[str] = []

        async def on_dispatch(_decision_id, context) -> None:
            dispatched.append(context.trigger)

        context = self._context()
        first = await coordinator.plan(context, on_dispatch=on_dispatch)
        self.assertEqual("PLANNED", first.status)
        self.assertEqual(0, first.model_requests)
        self.assertEqual(["SESSION_STARTED"], dispatched)
        self.assertGreaterEqual(len(first.directives), 1)

        repeated = await coordinator.plan(context, on_dispatch=on_dispatch)
        self.assertEqual("SKIPPED", repeated.status)
        self.assertEqual("BACKGROUND_OBSERVATION_ALREADY_PLANNED", repeated.reason_code)

    async def test_budget_enforces_three_calls_and_ten_minute_interval(self) -> None:
        policy = PlanningBudgetPolicy()
        budget = InMemoryPlanningBudget(policy)
        session_id, device_id = uuid4(), "kiosk-a"
        first_time = datetime(2026, 8, 30, 0, 0, tzinfo=UTC)
        self.assertTrue(budget.reserve(session_id=session_id, device_id=device_id, now=first_time).allowed)
        too_soon = budget.reserve(session_id=session_id, device_id=device_id, now=first_time + timedelta(minutes=9))
        self.assertFalse(too_soon.allowed)
        self.assertEqual("BACKGROUND_PLANNING_INTERVAL_NOT_ELAPSED", too_soon.reason_code)
        self.assertTrue(budget.reserve(session_id=session_id, device_id=device_id, now=first_time + timedelta(minutes=10)).allowed)
        self.assertTrue(budget.reserve(session_id=session_id, device_id=device_id, now=first_time + timedelta(minutes=20)).allowed)
        exhausted = budget.reserve(session_id=session_id, device_id=device_id, now=first_time + timedelta(minutes=30))
        self.assertFalse(exhausted.allowed)
        self.assertEqual("SESSION_BACKGROUND_BUDGET_EXHAUSTED", exhausted.reason_code)

    async def test_model_payload_failure_is_a_public_degradation_reason(self) -> None:
        payload_error = type("DeepSeekPayloadError", (ValueError,), {})()
        outcome = await BackgroundPlanningCoordinator(
            planner=_FailingPlanner(payload_error),
        ).plan(self._context())
        self.assertEqual("DEGRADED", outcome.status)
        self.assertEqual("BACKGROUND_MODEL_PAYLOAD_INVALID", outcome.reason_code)

    def test_sanitizer_only_keeps_consented_profile_summary(self) -> None:
        sanitizer = PlanningContextSanitizer()
        guest = sanitizer.sanitize(self._context())
        self.assertIsNone(guest.profile_summary)
        self.assertNotIn("token", str(guest.external_context))
        consented = sanitizer.sanitize(self._context(version=3, consent=True))
        self.assertEqual({"major": "图书情报"}, consented.profile_summary)
        self.assertNotIn("user_id", str(consented.profile_summary))

    def test_directive_validator_rejects_arbitrary_fields_and_actions(self) -> None:
        validator = DirectiveValidator()
        valid = validator.validate((WorkspaceDirectiveProposal(
            "SUGGEST_NEXT_ACTION", "global", "SUGGESTION",
            {"label": "查看图谱", "action": "OPEN_GRAPH"},
            "CONTEXT_READY", 0.8, ("workspace:context",), True,
        ),))
        self.assertEqual("SUGGEST_NEXT_ACTION", valid[0].directive_type)
        with self.assertRaises(DirectiveValidationError):
            validator.validate(({
                "type": "SUGGEST_NEXT_ACTION", "scope": "global", "behavior": "SUGGESTION",
                "payload": {"action": "EXECUTE_ARBITRARY_DOM", "html": "<script>"},
                "reason_code": "UNSAFE", "confidence": 0.9,
                "evidence_refs": ["workspace:context"], "reversible": True,
            },))

    async def test_workspace_emits_real_background_policy_events(self) -> None:
        coordinator = BackgroundPlanningCoordinator(planner=FixtureBackgroundPlanner())
        broker = AgentWorkspaceBroker(background_planner=coordinator)
        created, _ = broker.create(session_id=uuid4(), user_id=9000001, mode="guest")
        workspace_id = UUID(str(created["workspace_id"]))
        await broker.wait_for_idle()
        snapshot = broker.snapshot(workspace_id, user_id=9000001)
        events = snapshot["recent_events"]
        starts = [event for event in events if event.get("event_type") == "AGENT_STARTED" and event.get("action") == "BACKGROUND_PLAN"]
        terminals = [event for event in events if event.get("event_type") in {"AGENT_COMPLETED", "AGENT_FAILED"} and event.get("action") == "BACKGROUND_PLAN"]
        self.assertTrue(starts)
        self.assertTrue(terminals)
        self.assertEqual("RecommendationPolicyAgent", starts[-1]["agent_name"])
        self.assertTrue(any(item["type"] == "SUGGEST_TOPICS" for item in snapshot["directives"]))
        self.assertEqual("PLANNED", snapshot["context_summary"]["background_planning"]["status"])
        self.assertEqual(0, sum(int(event.get("llm_requests", 0)) for event in events))

    async def test_authenticated_consent_sends_only_bounded_profile_summary(self) -> None:
        planner = _CapturingPlanner()
        reader = _ProfileReader()
        coordinator = BackgroundPlanningCoordinator(planner=planner)
        broker = AgentWorkspaceBroker(
            background_planner=coordinator,
            profile_reader=reader,
        )
        created, _ = broker.create(
            session_id=uuid4(),
            user_id=10001,
            mode="authenticated",
            personalization_enabled=True,
        )
        await broker.wait_for_idle()
        self.assertEqual([10001, 10001], reader.calls)
        self.assertTrue(planner.contexts)
        profile = planner.contexts[0].profile_summary
        self.assertEqual({"major": "图书情报", "profile_version": "v1"}, profile)

    async def test_guest_background_planning_never_reads_profile(self) -> None:
        planner = _CapturingPlanner()
        reader = _ProfileReader()
        broker = AgentWorkspaceBroker(
            background_planner=BackgroundPlanningCoordinator(planner=planner),
            profile_reader=reader,
        )
        broker.create(session_id=uuid4(), user_id=9000002, mode="guest")
        await broker.wait_for_idle()
        self.assertEqual([], reader.calls)
        self.assertTrue(planner.contexts)
        self.assertIsNone(planner.contexts[0].profile_summary)


if __name__ == "__main__":
    unittest.main()
