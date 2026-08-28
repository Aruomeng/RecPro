from __future__ import annotations

import asyncio
import unittest
from uuid import UUID, uuid4

from backend.app.agent_workspace import AgentWorkspaceBroker, SessionTopicGraph
from backend.app.agent_workspace.dispatcher import WorkspaceObservationCapacityError
from backend.app.agent_workspace.ports.handlers import WorkspaceAgentResult
from backend.app.agent_workspace.adapters.profile_reader import MySQLWorkspaceProfileReader


class _ReadTools:
    def __init__(self) -> None:
        self.graph_calls: list[tuple[str, int]] = []
        self.resource_calls: list[int] = []

    async def graph_neighbors(self, entity_id: str, *, limit: int):
        self.graph_calls.append((entity_id, limit))
        return {"nodes": [{"id": entity_id}, {"id": "topic:next"}], "edges": []}

    async def resource(self, resource_id: int):
        self.resource_calls.append(resource_id)
        return {"resource_id": resource_id, "title": "证据约束推荐"}


class _ProfileReader:
    def __init__(self) -> None:
        self.calls: list[int] = []

    async def summary(self, user_id: int):
        self.calls.append(user_id)
        return {"profile_version": "profile-g2-v1:test", "confidence": 0.81}


class _SlowHandler:
    agent_name = "IntentUnderstandingAgent"
    observation_types = frozenset({"QUERY_SUBMITTED"})

    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.versions: list[int] = []

    async def handle(self, observation, _context):
        self.versions.append(observation.context_version)
        await self.release.wait()
        return WorkspaceAgentResult(
            agent_name=self.agent_name,
            action="RETURN_RESULT",
            target="RecommendationOrchestrator",
            reason_code="TEST_QUERY",
            confidence=0.9,
            evidence_refs=("session:query",),
        )


class AgentWorkspaceV2Tests(unittest.IsolatedAsyncioTestCase):
    async def test_profile_adapter_is_rollback_only_and_connection_on_use(self) -> None:
        class Cursor:
            def __init__(self) -> None:
                self.queries: list[str] = []
            async def __aenter__(self): return self
            async def __aexit__(self, *_args): return None
            async def execute(self, query, _params): self.queries.append(query)
            async def fetchall(self): return []
        class Connection:
            def __init__(self) -> None:
                self.reader = Cursor(); self.rollbacks = 0; self.closed = False
            def cursor(self): return self.reader
            async def rollback(self): self.rollbacks += 1
            def close(self): self.closed = True
        connection = Connection()
        calls = 0
        async def factory():
            nonlocal calls
            calls += 1
            return connection
        reader = MySQLWorkspaceProfileReader(factory)
        self.assertEqual(0, calls)

        summary = await reader.summary(10_000)

        self.assertEqual(1, calls)
        self.assertEqual(1, connection.rollbacks)
        self.assertTrue(connection.closed)
        self.assertTrue(all(query.lstrip().upper().startswith("SELECT") for query in connection.reader.queries))
        self.assertEqual(0, summary["event_count"])

    async def test_real_read_tools_emit_decision_tool_and_evidence_events(self) -> None:
        tools = _ReadTools()
        broker = AgentWorkspaceBroker(read_tools=tools)
        created, _ = broker.create(session_id=uuid4(), user_id=9_000_001, mode="guest")
        workspace_id = UUID(str(created["workspace_id"]))
        await broker.wait_for_idle()

        broker.observe(
            workspace_id,
            user_id=9_000_001,
            event_type="GRAPH_NODE_SELECTED",
            idempotency_key=str(uuid4()),
            payload={"entity_id": "topic:mas", "label": "多智能体系统"},
        )
        await broker.wait_for_idle()
        snapshot = broker.snapshot(workspace_id, user_id=9_000_001)

        self.assertEqual([("topic:mas", 40)], tools.graph_calls)
        semantic = next(agent for agent in snapshot["agents"] if agent["name"] == "ResourceSemanticAgent")
        self.assertEqual("COMPLETED", semantic["state"])
        self.assertEqual("SEMANTIC_CONTEXT_VERIFIED", semantic["reason_code"])
        events = snapshot["recent_events"]
        started = [event for event in events if event["event_type"] == "AGENT_STARTED" and event.get("agent_name") == "ResourceSemanticAgent"]
        tools_used = [event for event in events if event["event_type"] == "AGENT_TOOL_CALL" and event.get("agent_name") == "ResourceSemanticAgent"]
        self.assertTrue(started and started[-1].get("decision_id"))
        self.assertEqual("neo4j_public_neighbors", tools_used[-1]["tool_call"]["tool"])
        self.assertEqual(0, sum(int(event.get("llm_requests", 0)) for event in events))

    async def test_guest_never_dispatches_or_reads_profile_but_consented_user_does(self) -> None:
        profile = _ProfileReader()
        guest = AgentWorkspaceBroker(profile_reader=profile)
        guest_snapshot, _ = guest.create(session_id=uuid4(), user_id=9_000_001, mode="guest")
        await guest.wait_for_idle()
        self.assertEqual([], profile.calls)
        guest_user_agent = next(agent for agent in guest.snapshot(UUID(str(guest_snapshot["workspace_id"])), user_id=9_000_001)["agents"] if agent["name"] == "UserProfileAgent")
        self.assertEqual("IDLE", guest_user_agent["state"])

        authenticated = AgentWorkspaceBroker(profile_reader=profile)
        auth_snapshot, _ = authenticated.create(
            session_id=uuid4(), user_id=10_000, mode="authenticated",
            personalization_enabled=True,
        )
        await authenticated.wait_for_idle()
        self.assertEqual([10_000], profile.calls)
        auth_user_agent = next(agent for agent in authenticated.snapshot(UUID(str(auth_snapshot["workspace_id"])), user_id=10_000)["agents"] if agent["name"] == "UserProfileAgent")
        self.assertEqual("COMPLETED", auth_user_agent["state"])

    async def test_per_workspace_fifo_and_global_pending_bound(self) -> None:
        handler = _SlowHandler()
        broker = AgentWorkspaceBroker(
            handlers=(handler,), max_pending_observations=2,
        )
        created, _ = broker.create(session_id=uuid4(), user_id=9_000_001, mode="guest")
        workspace_id = UUID(str(created["workspace_id"]))
        await broker.wait_for_idle()
        broker.observe(
            workspace_id, user_id=9_000_001, event_type="QUERY_SUBMITTED",
            idempotency_key=str(uuid4()), payload={"query": "first"},
        )
        broker.observe(
            workspace_id, user_id=9_000_001, event_type="QUERY_SUBMITTED",
            idempotency_key=str(uuid4()), payload={"query": "second"},
        )
        with self.assertRaises(WorkspaceObservationCapacityError):
            broker.observe(
                workspace_id, user_id=9_000_001, event_type="QUERY_SUBMITTED",
                idempotency_key=str(uuid4()), payload={"query": "third"},
            )
        await asyncio.sleep(0)
        self.assertEqual(1, len(handler.versions))
        handler.release.set()
        await broker.wait_for_idle()
        self.assertEqual(sorted(handler.versions), handler.versions)
        self.assertEqual(2, len(handler.versions))

    def test_topic_graph_is_deterministic_and_bounded(self) -> None:
        graph = SessionTopicGraph(max_nodes=4, max_edges=4)
        for index in range(12):
            graph.observe(
                "QUERY_SUBMITTED",
                {"query": f"主题 {index}", "topics": [f"主题{index}"]},
                observed_at=f"2026-08-28T10:00:{index:02d}Z",
            )
        snapshot = graph.snapshot()
        self.assertLessEqual(len(snapshot["nodes"]), 4)
        self.assertLessEqual(len(snapshot["edges"]), 4)
        self.assertTrue(snapshot["truncated"])


if __name__ == "__main__":
    unittest.main()
