from __future__ import annotations

from datetime import UTC, datetime
import unittest
from uuid import UUID

from scripts.verify_g4_readonly_fusion_runtime import (
    GRAPH_VERSION,
    build_parser,
    build_request,
    format_evaluation_at,
    parse_evaluation_at,
)
from backend.app.shared_kernel.contracts.graph_evidence import (
    build_graph_path_reference,
)
from scripts.g4_graph_evidence_contract import validate_v2_ranked_candidates


class G4ReadonlyRuntimeContractTests(unittest.TestCase):
    def test_readonly_runtime_defaults_to_a_bounded_180_second_deadline(self) -> None:
        args = build_parser().parse_args(["--run-id", "g4-readonly-contract-001"])
        self.assertEqual(180.0, args.deadline_seconds)
        self.assertEqual(
            ".env.neo4j-readonly-final.local", args.graph_env_file.name
        )
        self.assertEqual("lib-books-v2-20260828", GRAPH_VERSION)

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

    def test_parser_can_require_v2_path_evidence(self) -> None:
        args = build_parser().parse_args(
            ["--run-id", "g4-readonly-contract-004", "--require-v2-graph-paths"]
        )
        self.assertTrue(args.require_v2_graph_paths)

    def test_v2_coverage_accepts_covered_graph_and_explicit_non_graph_degrade(self) -> None:
        reference = build_graph_path_reference(
            graph_version=GRAPH_VERSION,
            node_ids=("topic:ai", "book:1"),
            edge_ids=("edge:1",),
        )
        summary = validate_v2_ranked_candidates(
            [
                {
                    "channel": "MYSQL+GRAPH",
                    "channel_scores": {"MYSQL": 0.6, "GRAPH": 1.0},
                    "kg_score": 1.0,
                    "graph_path_refs": [reference],
                    "graph_version": GRAPH_VERSION,
                    "graph_path_coverage_state": "COVERED",
                },
                {
                    "channel": "MYSQL+VECTOR",
                    "channel_scores": {"MYSQL": 0.7, "VECTOR": 0.8},
                    "kg_score": None,
                    "graph_path_refs": [],
                    "graph_version": GRAPH_VERSION,
                    "graph_path_coverage_state": "DEGRADED",
                },
            ],
            graph_version=GRAPH_VERSION,
            require_graph_paths=True,
        )
        self.assertEqual(1, summary["graph_scored_candidates"])
        self.assertEqual(1.0, summary["coverage_ratio"])

    def test_v2_coverage_rejects_legacy_reference(self) -> None:
        with self.assertRaisesRegex(ValueError, "not routeable"):
            validate_v2_ranked_candidates(
                [{
                    "channel": "MYSQL+GRAPH",
                    "channel_scores": {"MYSQL": 0.6, "GRAPH": 1.0},
                    "kg_score": 1.0,
                    "graph_path_refs": ["graphpath:" + "a" * 32],
                    "graph_version": GRAPH_VERSION,
                    "graph_path_coverage_state": "COVERED",
                }],
                graph_version=GRAPH_VERSION,
                require_graph_paths=True,
            )


if __name__ == "__main__":
    unittest.main()
