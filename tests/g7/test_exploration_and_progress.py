from __future__ import annotations

import asyncio
import unittest
from uuid import uuid4

from backend.app.exploration.graph_reader import PublicGraphReader
from backend.app.exploration.mysql_reader import MySQLCatalogReader
from backend.app.exploration.service import ExplorationService
from backend.app.recommendation.progress import (
    RecommendationProgressBroker,
    RunCapacityError,
    RunIdempotencyConflictError,
    RunNotFoundError,
)


class PublicGraphBoundaryTests(unittest.TestCase):
    def reader(self) -> PublicGraphReader:
        return PublicGraphReader(
            endpoint="http://127.0.0.1:7474/db/neo4j/tx/commit",
            username="readonly",
            password="test-only",
            graph_version="lib-books-v1-20260810",
        )

    def test_view_filters_private_labels_properties_and_relationships(self) -> None:
        rows = [
            {"row": [
                "book:1", "Book", {"title": "多智能体", "source_file": "private.csv"},
                "edge:1", "HAS_TOPIC", "book:1", "topic:1",
                "topic:1", "Topic", {"name": "人工智能", "source_fingerprint": "private"},
            ]},
            {"row": [
                "source:1", "SourceFile", {"name": "secret"},
                "edge:2", "IMPORTED_FROM", "source:1", "book:1",
                "book:1", "Book", {"title": "多智能体"},
            ]},
        ]

        view = self.reader()._view(rows, query="agent", limit=60)

        self.assertEqual({"book:1", "topic:1"}, {node["id"] for node in view["nodes"]})
        self.assertEqual(["HAS_TOPIC"], [edge["type"] for edge in view["edges"]])
        for node in view["nodes"]:
            self.assertNotIn("source_file", node["properties"])
            self.assertNotIn("source_fingerprint", node["properties"])

    def test_view_never_exceeds_public_bounds(self) -> None:
        rows = []
        for index in range(150):
            rows.append({"row": [
                f"book:{index}", "Book", {"title": f"Book {index}"},
                f"edge:{index}", "HAS_TOPIC", f"book:{index}", f"topic:{index}",
                f"topic:{index}", "Topic", {"name": f"Topic {index}"},
            ]})
        view = self.reader()._view(rows, query="all", limit=60)
        self.assertLessEqual(len(view["nodes"]), 60)
        self.assertLessEqual(len(view["edges"]), 120)
        self.assertTrue(view["truncated"])

    def test_path_view_returns_only_bounded_public_multihop_evidence(self) -> None:
        rows = [
            {"row": [
                [
                    ["book:1", "Book", {"title": "多智能体系统", "source_file": "private.csv"}],
                    ["work:1", "Work", {"title": "多智能体系统"}],
                    ["topic:1", "Topic", {"name": "多智能体"}],
                ],
                [
                    ["edge:instance", "INSTANCE_OF", "book:1", "work:1"],
                    ["edge:topic", "HAS_TOPIC", "work:1", "topic:1"],
                ],
                2,
            ]},
            # This path is structurally valid but exceeds the caller's bound.
            {"row": [
                [
                    ["book:1", "Book", {"title": "多智能体系统"}],
                    ["work:1", "Work", {"title": "多智能体系统"}],
                    ["author:1", "Author", {"name": "作者"}],
                    ["topic:1", "Topic", {"name": "多智能体"}],
                ],
                [
                    ["edge:1", "INSTANCE_OF", "book:1", "work:1"],
                    ["edge:2", "AUTHORED_BY", "work:1", "author:1"],
                    ["edge:3", "HAS_TOPIC", "author:1", "topic:1"],
                ],
                3,
            ]},
        ]

        result = self.reader()._path_view(
            rows,
            source_id="book:1",
            target_id="topic:1",
            max_hops=2,
            limit=10,
        )

        self.assertEqual(1, len(result["paths"]))
        self.assertEqual(2, result["paths"][0]["hop_count"])
        self.assertEqual(0.85, result["paths"][0]["score"])
        self.assertTrue(result["paths"][0]["path_id"].startswith("graphpath:"))
        self.assertEqual({"Book", "Work", "Topic"}, {node["type"] for node in result["graph"]["nodes"]})
        self.assertTrue(all("source_file" not in node["properties"] for node in result["graph"]["nodes"]))

    def test_path_query_keeps_user_values_out_of_constant_cypher(self) -> None:
        class CapturingReader(PublicGraphReader):
            def _query(self, statement, parameters):
                self.statement = statement
                self.parameters = parameters
                return []

        reader = CapturingReader(
            endpoint="http://127.0.0.1:7474/db/neo4j/tx/commit",
            username="readonly",
            password="test-only",
            graph_version="lib-books-v2-20260828",
        )
        injection = "book:1') MATCH (secret) RETURN secret //"
        result = asyncio.run(reader.paths(injection, "topic:1", max_hops=3, limit=10))
        self.assertEqual([], result["paths"])
        self.assertNotIn(injection, reader.statement)
        self.assertEqual(injection, reader.parameters["source_id"])
        self.assertIn("*1..3", reader.statement)

    def test_path_bounds_are_fail_closed(self) -> None:
        reader = self.reader()
        for max_hops, limit in ((0, 1), (4, 1), (1, 0), (1, 11)):
            with self.assertRaises(ValueError):
                asyncio.run(reader.paths("book:1", "topic:1", max_hops=max_hops, limit=limit))


class ExplorationLayeringTests(unittest.IsolatedAsyncioTestCase):
    async def test_overview_cache_uses_ports_once(self) -> None:
        class Catalog:
            calls = 0
            async def overview(self):
                self.calls += 1
                return {"totals": {"resources": 1, "books": 1, "papers": 0, "tags": 1}, "availability": [], "categories": [], "publication_decades": [], "popular_topics": []}
        class Graph:
            calls = 0
            async def stats(self): self.calls += 1; return {"nodes": 2, "relationships": 1}
        catalog, graph = Catalog(), Graph()
        service = ExplorationService(catalog_reader=catalog, graph_reader=graph, cache_seconds=300)
        first, second = await service.overview(), await service.overview()
        self.assertEqual(first["totals"], second["totals"])
        self.assertEqual(1, catalog.calls)
        self.assertEqual(1, graph.calls)

    async def test_mysql_overview_executes_only_selects_and_rolls_back(self) -> None:
        class Cursor:
            def __init__(self): self.queries = []; self.index = 0
            async def __aenter__(self): return self
            async def __aexit__(self, *_): return None
            async def execute(self, query, _params=None): self.queries.append(query); self.index += 1
            async def fetchone(self): return (3, 2, 1) if self.index == 1 else (5,)
            async def fetchall(self):
                return {3: [("AVAILABLE_BORROW", 3)], 4: [("TP", 3)], 5: [(2020, 3)], 6: [("AI", 3)]}[self.index]
        class Connection:
            def __init__(self): self.reader = Cursor(); self.rolled_back = False; self.closed = False
            def cursor(self): return self.reader
            async def rollback(self): self.rolled_back = True
            def close(self): self.closed = True
        connection = Connection()
        adapter = MySQLCatalogReader(connection_factory=lambda: asyncio.sleep(0, result=connection))
        result = await adapter.overview()
        self.assertEqual(3, result["totals"]["resources"])
        self.assertTrue(connection.rolled_back)
        self.assertTrue(connection.closed)
        self.assertTrue(all(query.lstrip().upper().startswith("SELECT") for query in connection.reader.queries))


class RecommendationProgressBrokerTests(unittest.IsolatedAsyncioTestCase):
    async def test_ordered_reconnect_and_terminal_state(self) -> None:
        broker = RecommendationProgressBroker(max_concurrent=2, retention_seconds=600)
        task_id, trace_id = uuid4(), uuid4()
        sink, replayed = broker.reserve(task_id=task_id, trace_id=trace_id, context_version=1, user_id=1001, request_fingerprint="same-request")
        self.assertFalse(replayed)
        sink.publish("AGENT_STARTED", {"agent_name": "IntentUnderstandingAgent", "status": "UNDERSTANDING"})
        sink.publish("AGENT_COMPLETED", {"agent_name": "IntentUnderstandingAgent", "status": "DECIDING"})
        broker.complete(task_id, result={"status": "COMPLETED"}, replayed=False)

        events = [event async for event in broker.events(task_id, user_id=1001, after_sequence=1)]
        self.assertEqual([2, 3, 4], [event["sequence"] for event in events if event])
        self.assertEqual("TASK_COMPLETED", events[-1]["event_type"])
        self.assertTrue(broker.state(task_id, user_id=1001)["terminal"])

    async def test_capacity_and_user_visibility_are_bounded(self) -> None:
        broker = RecommendationProgressBroker(max_concurrent=1, retention_seconds=600)
        first = uuid4()
        broker.reserve(task_id=first, trace_id=uuid4(), context_version=1, user_id=1001, request_fingerprint="first-request")
        with self.assertRaises(RunCapacityError):
            broker.reserve(task_id=uuid4(), trace_id=uuid4(), context_version=1, user_id=1001, request_fingerprint="second-request")
        with self.assertRaises(RunNotFoundError):
            broker.state(first, user_id=1002)

    async def test_event_buffer_is_capped_at_256(self) -> None:
        broker = RecommendationProgressBroker(max_concurrent=1, retention_seconds=600)
        task_id = uuid4()
        sink, _ = broker.reserve(task_id=task_id, trace_id=uuid4(), context_version=1, user_id=1001, request_fingerprint="buffer-request")
        for index in range(300):
            sink.publish("STATE_CHANGED", {"status": f"S{index}"})
        broker.complete(task_id, result={"status": "COMPLETED"}, replayed=False)
        events = [event async for event in broker.events(task_id, user_id=1001)]
        self.assertEqual(256, len(events))
        self.assertGreater(events[0]["sequence"], 1)

    async def test_same_identity_rejects_a_different_payload_fingerprint(self) -> None:
        broker = RecommendationProgressBroker(max_concurrent=1, retention_seconds=600)
        task_id = uuid4()
        broker.reserve(task_id=task_id, trace_id=uuid4(), context_version=1, user_id=1001, request_fingerprint="payload-a")
        with self.assertRaises(RunIdempotencyConflictError):
            broker.reserve(task_id=task_id, trace_id=uuid4(), context_version=1, user_id=1001, request_fingerprint="payload-b")


if __name__ == "__main__":
    unittest.main()
