from __future__ import annotations

import unittest

from backend.app.shared_kernel.contracts.graph_evidence import (
    build_graph_path_reference,
)
from scripts.g4_graph_evidence_contract import (
    REQUIRED_CANDIDATE_ENRICHMENT,
    V2_GRAPH_VERSION,
    validate_v2_http_items,
    validate_v2_readonly_evidence,
)


def path_reference() -> str:
    return build_graph_path_reference(
        graph_version=V2_GRAPH_VERSION,
        node_ids=("topic:ai", "work:one", "book:one"),
        edge_ids=("edge:topic", "edge:instance"),
    )


class G4GraphEvidenceContractTests(unittest.TestCase):
    def test_public_items_require_covered_routeable_evidence_for_graph_score(self) -> None:
        summary = validate_v2_http_items(
            [{
                "evidence": {
                    "channels": ["MYSQL", "GRAPH"],
                    "channel_scores": {"MYSQL": 0.6, "GRAPH": 0.85},
                    "graph_path_refs": [path_reference()],
                    "graph_version": V2_GRAPH_VERSION,
                    "graph_path_coverage_state": "COVERED",
                }
            }],
            require_graph_paths=True,
        )
        self.assertEqual(1, summary["covered_candidates"])

    def test_public_items_reject_graph_score_without_path(self) -> None:
        with self.assertRaisesRegex(ValueError, "lacks covered path evidence"):
            validate_v2_http_items(
                [{
                    "evidence": {
                        "channels": ["MYSQL", "GRAPH"],
                        "channel_scores": {"MYSQL": 0.6, "GRAPH": 0.85},
                        "graph_path_refs": [],
                        "graph_version": V2_GRAPH_VERSION,
                        "graph_path_coverage_state": "DEGRADED",
                    }
                }],
                require_graph_paths=True,
            )

    def test_readonly_receipt_binds_enrichment_coverage_and_zero_llm(self) -> None:
        receipt = validate_v2_readonly_evidence(
            {
                "versions": {"graph_version": V2_GRAPH_VERSION},
                "candidate_enrichment": {
                    field: True for field in REQUIRED_CANDIDATE_ENRICHMENT
                },
                "graph_path_coverage": {
                    "graph_version": V2_GRAPH_VERSION,
                    "graph_scored_candidates": 2,
                    "covered_candidates": 2,
                    "degraded_candidates": 1,
                    "coverage_ratio": 1.0,
                    "routeable_path_reference_count": 3,
                    "required": True,
                },
                "safety": {"deepseek_requests": 0},
            }
        )
        self.assertEqual(2, receipt["graph_scored_candidates"])

    def test_readonly_receipt_rejects_nonzero_llm_or_partial_coverage(self) -> None:
        base = {
            "versions": {"graph_version": V2_GRAPH_VERSION},
            "candidate_enrichment": {
                field: True for field in REQUIRED_CANDIDATE_ENRICHMENT
            },
            "graph_path_coverage": {
                "graph_version": V2_GRAPH_VERSION,
                "graph_scored_candidates": 2,
                "covered_candidates": 1,
                "coverage_ratio": 0.5,
                "routeable_path_reference_count": 1,
            },
            "safety": {"deepseek_requests": 0},
        }
        with self.assertRaisesRegex(ValueError, "100% routeable"):
            validate_v2_readonly_evidence(base)
        base["graph_path_coverage"] = {
            **base["graph_path_coverage"],
            "covered_candidates": 2,
            "coverage_ratio": 1.0,
        }
        base["safety"] = {"deepseek_requests": 1}
        with self.assertRaisesRegex(ValueError, "zero DeepSeek"):
            validate_v2_readonly_evidence(base)


if __name__ == "__main__":
    unittest.main()
