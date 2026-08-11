from __future__ import annotations

import unittest

from scripts.build_g4_recommendation_projection_plan import count_targets
from scripts.g4_projection_contract import validate_g4_projection_query_spec


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

    def test_query_spec_accepts_bounded_deadline_metadata(self) -> None:
        value = validate_g4_projection_query_spec(
            {
                "input_text": "多智能体系统与智慧图书馆",
                "resource_types": ["BOOK"],
                "output_type": "TOPIC_RESOURCES",
                "limit": 8,
                "deadline_seconds": 240.0,
            }
        )
        self.assertEqual(240.0, value["deadline_seconds"])

    def test_query_spec_rejects_semantic_or_metadata_drift(self) -> None:
        with self.assertRaises(ValueError):
            validate_g4_projection_query_spec(
                {
                    "input_text": "其他主题",
                    "resource_types": ["BOOK"],
                    "output_type": "TOPIC_RESOURCES",
                    "limit": 8,
                }
            )
        with self.assertRaises(ValueError):
            validate_g4_projection_query_spec(
                {
                    "input_text": "多智能体系统与智慧图书馆",
                    "resource_types": ["BOOK"],
                    "output_type": "TOPIC_RESOURCES",
                    "limit": 8,
                    "deadline_seconds": 301,
                }
            )


if __name__ == "__main__":
    unittest.main()
