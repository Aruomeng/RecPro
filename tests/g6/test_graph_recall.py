from __future__ import annotations

import asyncio
from pathlib import Path
import unittest

from backend.app.catalog.adapters.neo4j import Neo4jGraphReader


class FixtureGraphReader(Neo4jGraphReader):
    def _run_query(self, parameters):
        self.parameters = parameters
        return [{"row": ["book:one", 0.75, ["多智能体"]]}]


class FixtureV2GraphReader(Neo4jGraphReader):
    def _run_query(self, parameters, statement):
        self.parameters = parameters
        self.statement = statement
        return [{"row": ["book:one", [
            {
                "matched_term": "多智能体",
                "hop_count": 1,
                "node_ids": ["book:one", "topic:agent"],
                "edge_ids": ["edge:direct"],
            },
            {
                "matched_term": "知识图谱",
                "hop_count": 3,
                "node_ids": ["book:one", "work:one", "category:tp", "topic:kg"],
                "edge_ids": ["edge:i", "edge:c", "edge:t"],
            },
            # Invalid/unbounded evidence must never contribute.
            {
                "matched_term": "多智能体",
                "hop_count": 4,
                "node_ids": ["a", "b", "c", "d", "e"],
                "edge_ids": ["1", "2", "3", "4"],
            },
        ]]}]


class GraphRecallTests(unittest.TestCase):
    def test_reader_is_parameterized_and_returns_stable_evidence(self) -> None:
        reader = FixtureGraphReader(
            endpoint="http://127.0.0.1:62675/db/neo4j/tx/commit",
            username="neo4j",
            password="local-test-password",
        )
        result = asyncio.run(
            reader.recall(
                terms=("多智能体", "多智能体"),
                graph_version="lib-books-v1-20260810",
                limit=5,
            )
        )
        self.assertEqual(1, len(result))
        self.assertEqual("book:one", result[0].external_id)
        self.assertEqual(0.75, result[0].score)
        self.assertEqual(("多智能体",), result[0].matched_terms)
        self.assertEqual(["多智能体"], reader.parameters["terms"])

    def test_reader_rejects_unbounded_input(self) -> None:
        reader = FixtureGraphReader(
            endpoint="http://127.0.0.1:62675/db/neo4j/tx/commit",
            username="neo4j",
            password="local-test-password",
        )
        with self.assertRaises(ValueError):
            asyncio.run(
                reader.recall(
                    terms=tuple(str(index) for index in range(17)),
                    graph_version="lib-books-v1-20260810",
                    limit=5,
                )
            )

    def test_v2_reader_requires_valid_paths_and_applies_hop_decay(self) -> None:
        reader = FixtureV2GraphReader(
            endpoint="http://127.0.0.1:62675/db/neo4j/tx/commit",
            username="readonly",
            password="test-only",
        )
        result = asyncio.run(reader.recall(
            terms=("多智能体", "知识图谱"),
            graph_version="lib-books-v2-20260828",
            limit=5,
        ))
        self.assertEqual(1.0, result[0].score)
        self.assertEqual(("多智能体", "知识图谱"), result[0].matched_terms)
        self.assertEqual(2, len(result[0].graph_path_refs))
        self.assertTrue(all(ref.startswith("graphpath:") for ref in result[0].graph_path_refs))
        self.assertIn("*1..3", reader.statement)
        self.assertNotIn("多智能体", reader.statement)

    def test_reader_does_not_expose_write_statements(self) -> None:
        source = Path("backend/app/catalog/adapters/neo4j.py").read_text(encoding="utf-8")
        self.assertNotIn("INSERT", source.upper())
        self.assertNotIn("MERGE", source.upper())
        self.assertNotIn("SET ", source.upper())


if __name__ == "__main__":
    unittest.main()
