from __future__ import annotations

import unittest

from backend.app.shared_kernel.contracts.graph_evidence import (
    build_graph_path_reference,
    is_graph_path_reference,
    is_routeable_graph_path_reference,
    parse_graph_path_route,
)


class GraphPathReferenceTests(unittest.TestCase):
    def test_v2_reference_is_stable_routeable_and_contains_no_raw_entity_id(self) -> None:
        reference = build_graph_path_reference(
            graph_version="lib-books-v2-20260828",
            node_ids=("topic:多智能体", "work:one", "book:one"),
            edge_ids=("edge:topic", "edge:instance"),
        )
        self.assertEqual(
            reference,
            build_graph_path_reference(
                graph_version="lib-books-v2-20260828",
                node_ids=("topic:多智能体", "work:one", "book:one"),
                edge_ids=("edge:topic", "edge:instance"),
            ),
        )
        self.assertNotIn("多智能体", reference)
        self.assertTrue(is_graph_path_reference(reference))
        self.assertTrue(is_routeable_graph_path_reference(reference))
        route = parse_graph_path_route(reference)
        self.assertIsNotNone(route)
        self.assertEqual("topic:多智能体", route.source_id)
        self.assertEqual("book:one", route.target_id)

    def test_legacy_reference_remains_valid_but_has_no_route(self) -> None:
        reference = "graphpath:" + "a" * 32
        self.assertTrue(is_graph_path_reference(reference))
        self.assertFalse(is_routeable_graph_path_reference(reference))
        self.assertIsNone(parse_graph_path_route(reference))

    def test_reference_rejects_non_v2_unbounded_and_tampered_shapes(self) -> None:
        with self.assertRaises(ValueError):
            build_graph_path_reference(
                graph_version="lib-books-v1-20260810",
                node_ids=("topic:one", "book:one"),
                edge_ids=("edge:one",),
            )
        with self.assertRaises(ValueError):
            build_graph_path_reference(
                graph_version="lib-books-v2-20260828",
                node_ids=("a", "b", "c", "d", "e"),
                edge_ids=("1", "2", "3", "4"),
            )
        self.assertFalse(is_graph_path_reference("graphpath:v2:not-valid"))


if __name__ == "__main__":
    unittest.main()
