from __future__ import annotations

import asyncio
from pathlib import Path
import unittest

from backend.app.catalog.adapters.neo4j import Neo4jGraphReader


class FixtureGraphReader(Neo4jGraphReader):
    def _run_query(self, parameters):
        self.parameters = parameters
        return [{"row": ["book:one", 0.75, ["多智能体"]]}]


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

    def test_reader_does_not_expose_write_statements(self) -> None:
        source = Path("backend/app/catalog/adapters/neo4j.py").read_text(encoding="utf-8")
        self.assertNotIn("INSERT", source.upper())
        self.assertNotIn("MERGE", source.upper())
        self.assertNotIn("SET ", source.upper())


if __name__ == "__main__":
    unittest.main()
