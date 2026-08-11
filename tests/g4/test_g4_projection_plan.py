from __future__ import annotations

import unittest

from scripts.build_g4_recommendation_projection_plan import count_targets


class G4ProjectionPlanTests(unittest.TestCase):
    def test_candidate_persistence_rows_drive_bounded_delta(self) -> None:
        targets = count_targets(candidate_rows=13)

        self.assertEqual("recommendation_task", targets[0][0])
        self.assertEqual(("recommendation_candidate", 13), targets[2])
        self.assertEqual(57, sum(delta for _table, delta in targets))

    def test_candidate_persistence_rows_rejects_unsafe_values(self) -> None:
        for value in (0, 61, True, False):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    count_targets(candidate_rows=value)


if __name__ == "__main__":
    unittest.main()
