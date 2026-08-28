from __future__ import annotations

import unittest

from scripts.build_book_graph_v2 import analyze, build_rows, dry_run_report


def node(graph_key: str, label: str, **properties: object) -> dict[str, object]:
    return {
        "entity_id": graph_key.split(":", 1)[-1],
        "graph_key": graph_key,
        "graph_version": "lib-books-v1-20260810",
        "label": label,
        "properties": properties,
    }


def edge(edge_key: str, source: str, predicate: str, target: str) -> dict[str, object]:
    return {
        "edge_key": edge_key,
        "subject_key": source,
        "predicate": predicate,
        "object_key": target,
        "properties": {},
    }


class BookGraphV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        prefix = "lib-books-v1-20260810:"
        self.nodes = [
            node(prefix + "book:1", "Book", title="Agent Systems", isbn="1", publisher="P1"),
            node(prefix + "book:2", "Book", title="Ａｇｅｎｔ systems", isbn="2", publisher="P2"),
            node(prefix + "book:3", "Book", title="Agent Systems"),
            node(prefix + "author:a", "Author", name="Author A"),
        ]
        self.triples = [
            edge("edge:1", prefix + "book:1", "AUTHORED_BY", prefix + "author:a"),
            edge("edge:2", prefix + "book:2", "AUTHORED_BY", prefix + "author:a"),
        ]

    def test_shared_title_and_author_merge_but_missing_author_does_not(self) -> None:
        analysis = analyze(self.nodes, self.triples)
        self.assertEqual(2, len(analysis.works))
        groups = sorted(len(work.book_keys) for work in analysis.works)
        self.assertEqual([1, 2], groups)
        reasons = {item["reason_code"] for item in analysis.proposals}
        self.assertIn("MISSING_AUTHOR_FOR_WORK_MERGE", reasons)
        self.assertIn("WORK_ISBN_CONFLICT", reasons)
        self.assertIn("WORK_PUBLISHER_CONFLICT", reasons)

    def test_v2_is_additive_and_never_invents_items(self) -> None:
        analysis = analyze(self.nodes, self.triples)
        target_nodes, target_triples = build_rows(
            self.nodes,
            self.triples,
            analysis,
            target_version="lib-books-v2-20260828",
        )
        self.assertEqual(len(self.nodes) + len(analysis.works), len(target_nodes))
        self.assertEqual(len(self.triples) + 3, len(target_triples))
        self.assertEqual(3, sum(row["predicate"] == "INSTANCE_OF" for row in target_triples))
        self.assertFalse(any(row["label"] == "Item" for row in target_nodes))
        self.assertTrue(all(row["graph_version"] == "lib-books-v2-20260828" for row in target_nodes))

    def test_dry_run_declares_zero_external_effects(self) -> None:
        report = dry_run_report(
            analyze(self.nodes, self.triples),
            target_version="lib-books-v2-20260828",
        )
        self.assertEqual(0, report["target"]["items"])
        self.assertEqual(0, report["review_proposals"]["persisted_rows"])
        self.assertTrue(all(value == 0 for value in report["safety"].values()))


if __name__ == "__main__":
    unittest.main()
