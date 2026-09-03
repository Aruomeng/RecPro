from __future__ import annotations

import unittest
from unittest.mock import patch

from scripts.build_g4_recommendation_projection_plan import (
    PROJECT_ROOT,
    count_targets,
    load_compose_identity,
)
from scripts.g4_projection_contract import (
    validate_g4_projection_query_spec,
    validate_g4_projection_request_matches_query_spec,
)


class G4ProjectionPlanTests(unittest.TestCase):
    @patch("scripts.build_g4_recommendation_projection_plan.validate_compose", return_value=())
    @patch("scripts.build_g4_recommendation_projection_plan.read_env")
    def test_plan_identity_is_bound_to_validated_compose_values(
        self, read_env, validate_compose
    ) -> None:
        read_env.return_value = {
            "COMPOSE_PROJECT_NAME": "isolated-project",
            "RECPRO_MYSQL_DATABASE": "recpro",
        }
        project, database = load_compose_identity(
            PROJECT_ROOT / "contracts" / "config" / "examples" / "rec-1.0.0.json"
        )
        self.assertEqual(("isolated-project", "recpro"), (project, database))
        validate_compose.assert_called_once()

    def test_candidate_persistence_rows_drive_bounded_delta(self) -> None:
        targets = count_targets(candidate_rows=13)

        self.assertEqual("recommendation_task", targets[0][0])
        self.assertEqual(("recommendation_candidate", 13), targets[2])
        self.assertEqual(57, sum(delta for _table, delta in targets))

    def test_positive_item_coverage_drives_item_deltas(self) -> None:
        targets = dict(count_targets(candidate_rows=7, item_rows=4))
        self.assertEqual(4, targets["recommendation_item"])
        self.assertEqual(4, targets["recommendation_item_explanation"])

    def test_candidate_persistence_rows_rejects_unsafe_values(self) -> None:
        for value in (0, 61, True, False):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    count_targets(candidate_rows=value)
        for value in (0, 21, True, False):
            with self.subTest(item_rows=value), self.assertRaises(ValueError):
                count_targets(candidate_rows=12, item_rows=value)

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

    def test_query_spec_accepts_bounded_reading_path(self) -> None:
        query_spec = {
            "input_text": "推荐系统与智慧图书馆",
            "resource_types": ["BOOK"],
            "output_type": "READING_PATH",
            "limit": 8,
        }
        self.assertEqual("READING_PATH", validate_g4_projection_query_spec(query_spec)["output_type"])
        validate_g4_projection_request_matches_query_spec(
            query_spec,
            input_text="推荐系统与智慧图书馆",
            resource_types=["BOOK"],
            output_type="READING_PATH",
            limit=8,
        )

    def test_query_spec_accepts_bounded_book_and_paper_set(self) -> None:
        query_spec = {
            "input_text": "多智能体、知识图谱和智慧图书馆",
            "resource_types": ["BOOK", "PAPER"],
            "output_type": "TOPIC_RESOURCES",
            "limit": 8,
        }
        validate_g4_projection_request_matches_query_spec(
            query_spec,
            input_text="多智能体、知识图谱和智慧图书馆",
            resource_types=["BOOK", "PAPER"],
            output_type="TOPIC_RESOURCES",
            limit=8,
        )

    def test_query_spec_rejects_semantic_or_metadata_drift(self) -> None:
        with self.assertRaises(ValueError):
            validate_g4_projection_query_spec(
                {
                    "input_text": "其他主题",
                    "resource_types": ["PAPER"],
                    "output_type": "TOPIC_RESOURCES",
                    "limit": 8,
                }
            )

    def test_planned_request_must_match_recall_evidence(self) -> None:
        query_spec = {
            "input_text": "多智能体系统与智慧图书馆",
            "resource_types": ["BOOK"],
            "output_type": "TOPIC_RESOURCES",
            "limit": 8,
            "deadline_seconds": 180.0,
        }
        validate_g4_projection_request_matches_query_spec(
            query_spec,
            input_text="多智能体系统与智慧图书馆",
            resource_types=["BOOK"],
            output_type="TOPIC_RESOURCES",
            limit=8,
        )
        with self.assertRaisesRegex(ValueError, "does not match"):
            validate_g4_projection_request_matches_query_spec(
                query_spec,
                input_text="多智能体 智慧图书馆",
                resource_types=["BOOK"],
                output_type="TOPIC_RESOURCES",
                limit=8,
            )

    def test_query_spec_rejects_out_of_bounds_deadline(self) -> None:
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

    def test_reading_path_requires_at_least_six_resources(self) -> None:
        with self.assertRaises(ValueError):
            validate_g4_projection_query_spec(
                {
                    "input_text": "推荐系统与智慧图书馆",
                    "resource_types": ["BOOK"],
                    "output_type": "READING_PATH",
                    "limit": 5,
                }
            )


if __name__ == "__main__":
    unittest.main()
