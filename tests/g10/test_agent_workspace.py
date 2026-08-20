from __future__ import annotations

import unittest
from uuid import UUID, uuid4

from backend.app.agent_workspace import (
    AGENT_NAMES,
    AgentWorkspaceBroker,
    WorkspaceCapacityError,
    WorkspaceNotFoundError,
)


class AgentWorkspaceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.broker = AgentWorkspaceBroker(max_workspaces=2, retention_seconds=600)
        self.session_id = uuid4()
        self.snapshot, self.replayed = self.broker.create(session_id=self.session_id, user_id=9000001, mode="guest")
        self.workspace_id = UUID(str(self.snapshot["workspace_id"]))

    def test_workspace_has_exact_real_role_catalog_and_no_persistence_port(self) -> None:
        self.assertFalse(self.replayed)
        self.assertEqual(set(AGENT_NAMES), {item["name"] for item in self.snapshot["agents"]})
        self.assertFalse(hasattr(self.broker, "connection"))
        self.assertFalse(hasattr(self.broker, "repository"))
        external = [item for item in self.snapshot["sources"] if item["kind"] == "EXTERNAL_DEMO"]
        self.assertEqual(3, len(external))
        self.assertTrue(all(item["expires_at"] for item in external))

    def test_session_creation_is_idempotent(self) -> None:
        replay, replayed = self.broker.create(session_id=self.session_id, user_id=9000001, mode="guest")
        self.assertTrue(replayed)
        self.assertEqual(str(self.workspace_id), replay["workspace_id"])

    def test_graph_observation_dispatches_semantic_and_policy_agents(self) -> None:
        snapshot, replayed = self.broker.observe(
            self.workspace_id,
            user_id=9000001,
            event_type="GRAPH_NODE_SELECTED",
            idempotency_key=str(uuid4()),
            payload={"label": "多智能体系统", "entity_id": "topic:1"},
        )
        self.assertFalse(replayed)
        states = {item["name"]: item for item in snapshot["agents"]}
        self.assertEqual("COMPLETED", states["ResourceSemanticAgent"]["state"])
        self.assertEqual("COMPLETED", states["RecommendationPolicyAgent"]["state"])
        suggestion = next(item for item in snapshot["directives"] if item["type"] == "SUGGEST_NEXT_ACTION")
        self.assertEqual("SEMANTIC_CONTEXT_AVAILABLE", suggestion["reason_codes"][0])

    def test_observation_replay_does_not_duplicate_events(self) -> None:
        key = str(uuid4())
        first, _ = self.broker.observe(self.workspace_id, user_id=9000001, event_type="ROUTE_CHANGED", idempotency_key=key, payload={"route": "/graph"})
        second, replayed = self.broker.observe(self.workspace_id, user_id=9000001, event_type="ROUTE_CHANGED", idempotency_key=key, payload={"route": "/graph"})
        self.assertTrue(replayed)
        self.assertEqual(first["context_version"], second["context_version"])
        self.assertEqual(len(first["recent_events"]), len(second["recent_events"]))

    def test_secret_fields_are_never_published(self) -> None:
        snapshot, _ = self.broker.observe(
            self.workspace_id, user_id=9000001, event_type="EXTERNAL_CONTEXT_UPDATED",
            idempotency_key=str(uuid4()), payload={"api_key": "secret", "prompt": "hidden", "source": "demo"},
        )
        serialized = str(snapshot["recent_events"])
        self.assertNotIn("hidden", serialized)
        self.assertNotIn("secret", serialized)

    def test_directive_actions_are_bounded_and_user_scoped(self) -> None:
        directive = self.snapshot["directives"][0]
        updated = self.broker.directive_action(
            self.workspace_id, user_id=9000001,
            directive_id=UUID(str(directive["directive_id"])), action="DISMISS",
        )
        self.assertEqual("DISMISSED", updated["status"])
        with self.assertRaises(WorkspaceNotFoundError):
            self.broker.snapshot(self.workspace_id, user_id=1001)

    def test_capacity_is_bounded(self) -> None:
        self.broker.create(session_id=uuid4(), user_id=9000001, mode="guest")
        with self.assertRaises(WorkspaceCapacityError):
            self.broker.create(session_id=uuid4(), user_id=9000001, mode="guest")

    def test_real_recommendation_event_updates_same_agent_state(self) -> None:
        self.broker.bridge_recommendation_event(
            self.workspace_id, user_id=9000001, event_type="AGENT_COMPLETED",
            payload={"agent_name": "RankingAgent", "action": "RETURN_RESULT", "target": "RecommendationOrchestrator", "reason_code": "RANKED", "confidence": 0.9, "duration_ms": 12},
        )
        snapshot = self.broker.snapshot(self.workspace_id, user_id=9000001)
        ranking = next(item for item in snapshot["agents"] if item["name"] == "RankingAgent")
        self.assertEqual("COMPLETED", ranking["state"])
        self.assertEqual(12, ranking["duration_ms"])

    def test_readiness_observation_updates_sources_and_affected_agents(self) -> None:
        snapshot, _ = self.broker.observe(
            self.workspace_id,
            user_id=9000001,
            event_type="READINESS_CHANGED",
            idempotency_key=str(uuid4()),
            payload={"degraded": ["neo4j", "llm"]},
        )
        sources = {item["source_id"]: item["status"] for item in snapshot["sources"]}
        agents = {item["name"]: item["state"] for item in snapshot["agents"]}
        self.assertEqual("DEGRADED", sources["neo4j"])
        self.assertEqual("UP", sources["mysql"])
        self.assertEqual("DEGRADED", agents["ResourceSemanticAgent"])
        self.assertEqual("DEGRADED", agents["ExplanationAgent"])

    async def test_event_stream_resumes_after_sequence(self) -> None:
        after = self.snapshot["recent_events"][-2]["sequence"]
        stream = self.broker.events(self.workspace_id, user_id=9000001, after_sequence=after)
        first = await anext(stream)
        self.assertGreater(first["sequence"], after)
        await stream.aclose()


if __name__ == "__main__":
    unittest.main()
