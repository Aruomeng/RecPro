from __future__ import annotations

from datetime import UTC, datetime
import unittest
from uuid import UUID

from scripts.verify_g4_readonly_fusion_runtime import (
    build_parser,
    build_request,
    format_evaluation_at,
    parse_evaluation_at,
)


class G4ReadonlyRuntimeContractTests(unittest.TestCase):
    def test_readonly_runtime_defaults_to_a_bounded_180_second_deadline(self) -> None:
        args = build_parser().parse_args(["--run-id", "g4-readonly-contract-001"])
        self.assertEqual(180.0, args.deadline_seconds)
        self.assertEqual(
            ".env.neo4j-readonly-final.local", args.graph_env_file.name
        )

    def test_request_uses_explicit_deadline_without_store_access(self) -> None:
        now = datetime.now(UTC)
        request = build_request(
            "g4-readonly-contract-002",
            user_id=1001,
            now=now,
            input_text="多智能体+推荐系统+知识图谱",
            resource_types=("BOOK",),
            output_type="TOPIC_RESOURCES",
            limit=8,
            deadline_seconds=240.0,
        )
        self.assertEqual(1001, request.user_id)
        self.assertIsInstance(request.task_id, UUID)
        self.assertEqual(240.0, (request.deadline_at - request.evaluation_at).total_seconds())

    def test_fixed_evaluation_horizon_is_timezone_aware_and_roundtrips(self) -> None:
        value = parse_evaluation_at("2030-01-20T15:02:00+00:00")
        self.assertEqual("2030-01-20T15:02:00.000Z", format_evaluation_at(value))

    def test_parser_supports_as_of_effect_assertion(self) -> None:
        args = build_parser().parse_args(
            [
                "--run-id",
                "g4-readonly-contract-003",
                "--evaluation-at",
                "2030-01-20T15:02:00Z",
                "--assert-resource-absent",
                "128",
            ]
        )
        self.assertEqual("2030-01-20T15:02:00Z", args.evaluation_at)
        self.assertEqual(128, args.assert_resource_absent)


if __name__ == "__main__":
    unittest.main()
