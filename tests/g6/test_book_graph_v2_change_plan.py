from __future__ import annotations

from pathlib import Path
import unittest

from scripts.build_book_graph_v2_change_plan import build_plan
from scripts.import_book_graph import PROJECT_ROOT, canonical_json, sha256_bytes


GRAPH_DIR = PROJECT_ROOT / "artifacts/verification/book-graph-v2/lib-books-v2-20260828"


class BookGraphV2ChangePlanTests(unittest.TestCase):
    def test_plan_binds_exact_artifacts_and_zero_destructive_budget(self) -> None:
        plan = build_plan(
            reviewed_commit="a" * 40,
            created_at="2026-08-28T19:00:00+08:00",
            graph_dir=GRAPH_DIR,
        )
        unsigned = dict(plan)
        actual_hash = str(unsigned.pop("plan_hash"))
        self.assertEqual(actual_hash, sha256_bytes(canonical_json(unsigned).encode()))
        self.assertEqual(78_129, plan["graph_append"]["nodes"])
        self.assertEqual(206_848, plan["graph_append"]["relationships"])
        self.assertEqual(0, plan["graph_append"]["items"])
        self.assertEqual(0, plan["graph_append"]["review_proposals_persisted"])
        self.assertTrue(all(value == 0 for value in plan["safety"].values()))

    def test_plan_rejects_uncommitted_or_wrong_graph_identity(self) -> None:
        with self.assertRaises(ValueError):
            build_plan(
                reviewed_commit="short",
                created_at="2026-08-28T19:00:00+08:00",
                graph_dir=GRAPH_DIR,
            )


if __name__ == "__main__":
    unittest.main()
