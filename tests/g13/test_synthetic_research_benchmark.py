from __future__ import annotations

import unittest

from scripts.build_synthetic_research_benchmark import build_benchmark


class SyntheticResearchBenchmarkTests(unittest.TestCase):
    def _resources(self) -> list[dict[str, object]]:
        values: list[dict[str, object]] = []
        for topic, base in (("推荐系统", 1), ("知识图谱", 20)):
            for offset in range(10):
                values.append({
                    "resource_id": base + offset,
                    "external_id": f"book:{base + offset}",
                    "topic": topic,
                })
        return values

    def test_simulator_is_deterministic_anonymous_and_metadata_only(self) -> None:
        first = build_benchmark(self._resources(), user_count=8, interactions_per_user=3, seed=7)
        second = build_benchmark(self._resources(), user_count=8, interactions_per_user=3, seed=7)
        self.assertEqual(first, second)
        users, events, tasks = first
        self.assertEqual(8, len(users))
        self.assertEqual(48, len(events))
        self.assertEqual(8, len(tasks))
        self.assertTrue(all(str(row["user_research_id"]).startswith("synthetic-u-") for row in users))
        self.assertTrue(all(row["origin"] == "SYNTHETIC_SIMULATOR" for row in events))
        self.assertTrue(all(row["label_origin"] == "SYNTHETIC_METADATA_PROXY" for row in tasks))
        self.assertNotIn("name", str(users).lower())


if __name__ == "__main__":
    unittest.main()
