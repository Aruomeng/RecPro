"""Shared fail-closed contract for Stage 2 v2 recommendation evidence.

The read-only verifier, ChangePlan builder, and approved append executor use
this single module so routeability and coverage rules cannot drift between
preflight and apply.  It performs validation only and has no storage or model
side effects.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from backend.app.shared_kernel.contracts.graph_evidence import (
    is_routeable_graph_path_reference,
)


V2_GRAPH_VERSION = "lib-books-v2-20260828"
V2_GRAPH_EVIDENCE_PRECONDITION = (
    "Stage 2 v2 Graph scoring requires 100% routeable graphpath:v2 evidence; "
    "queries remain bounded to 3 hops, 10 paths, 60 nodes, 120 edges, and 3 seconds"
)
V2_GRAPH_ZERO_LLM_PRECONDITION = (
    "Stage 2 graph evidence acceptance authorizes zero DeepSeek requests"
)
REQUIRED_CANDIDATE_ENRICHMENT = frozenset(
    {
        "channel_scores",
        "channel_ranks",
        "primary_channel",
        "evidence_confidence",
        "graph_path_refs",
        "graph_version",
        "graph_path_coverage_state",
    }
)


def _validate_entries(
    entries: Sequence[object],
    *,
    graph_version: str,
    require_graph_paths: bool,
    public_http_shape: bool,
) -> dict[str, object]:
    if graph_version != V2_GRAPH_VERSION:
        raise ValueError("v2 graph evidence must use the frozen Stage 2 graph version")
    graph_scored = 0
    covered = 0
    degraded = 0
    path_references: set[str] = set()
    for index, raw in enumerate(entries):
        if not isinstance(raw, Mapping):
            raise ValueError(f"candidate {index} is not an object")
        evidence: Mapping[str, Any]
        if public_http_shape:
            raw_evidence = raw.get("evidence")
            if not isinstance(raw_evidence, Mapping):
                raise ValueError(f"public item {index} has no evidence object")
            evidence = raw_evidence
            raw_channels = evidence.get("channels")
            if not isinstance(raw_channels, list) or any(
                not isinstance(value, str) or not value.strip() for value in raw_channels
            ):
                raise ValueError(f"public item {index} has invalid channels")
            channels = tuple(value.strip().upper() for value in raw_channels)
        else:
            evidence = raw
            channel = raw.get("channel")
            if not isinstance(channel, str) or not channel.strip():
                raise ValueError(f"candidate {index} has no channel contract")
            channels = tuple(
                part.strip().upper() for part in channel.split("+") if part.strip()
            )
        scores = evidence.get("channel_scores")
        if not isinstance(scores, Mapping):
            raise ValueError(f"candidate {index} has no channel score map")
        references = evidence.get("graph_path_refs")
        if not isinstance(references, list) or len(references) > 10:
            raise ValueError(f"candidate {index} has invalid graph path references")
        coverage = evidence.get("graph_path_coverage_state")
        candidate_graph_version = evidence.get("graph_version")
        has_graph = "GRAPH" in channels
        if has_graph:
            graph_scored += 1
            if candidate_graph_version != graph_version:
                raise ValueError(
                    f"candidate {index} Graph version differs from the frozen runtime"
                )
            if coverage != "COVERED" or not references:
                raise ValueError(
                    f"candidate {index} Graph score lacks covered path evidence"
                )
            if "GRAPH" not in scores:
                raise ValueError(f"candidate {index} Graph score is not explicitly recorded")
            if not public_http_shape and evidence.get("kg_score") is None:
                raise ValueError(f"candidate {index} Graph score is not explicitly recorded")
            if any(not is_routeable_graph_path_reference(ref) for ref in references):
                raise ValueError(f"candidate {index} Graph path is not routeable")
            covered += 1
            path_references.update(str(ref) for ref in references)
        else:
            if references or "GRAPH" in scores:
                raise ValueError(
                    f"candidate {index} exposes Graph evidence without Graph scoring"
                )
            if not public_http_shape and evidence.get("kg_score") is not None:
                raise ValueError(
                    f"candidate {index} exposes Graph evidence without Graph scoring"
                )
            if coverage == "DEGRADED":
                degraded += 1
            elif coverage != "NOT_USED":
                raise ValueError(
                    f"candidate {index} has an invalid non-Graph coverage state"
                )
    if graph_scored != covered:
        raise ValueError("v2 Graph path coverage is below 100 percent")
    if require_graph_paths and graph_scored == 0:
        raise ValueError("verification requires at least one v2 Graph-scored candidate")
    return {
        "graph_version": graph_version,
        "graph_scored_candidates": graph_scored,
        "covered_candidates": covered,
        "degraded_candidates": degraded,
        "coverage_ratio": 1.0 if graph_scored else None,
        "routeable_path_reference_count": len(path_references),
        "required": require_graph_paths,
    }


def validate_v2_ranked_candidates(
    candidates: Sequence[object],
    *,
    graph_version: str = V2_GRAPH_VERSION,
    require_graph_paths: bool = True,
) -> dict[str, object]:
    return _validate_entries(
        candidates,
        graph_version=graph_version,
        require_graph_paths=require_graph_paths,
        public_http_shape=False,
    )


def validate_v2_http_items(
    items: Sequence[object],
    *,
    graph_version: str = V2_GRAPH_VERSION,
    require_graph_paths: bool = True,
) -> dict[str, object]:
    return _validate_entries(
        items,
        graph_version=graph_version,
        require_graph_paths=require_graph_paths,
        public_http_shape=True,
    )


def validate_v2_readonly_evidence(
    evidence: Mapping[str, Any], *, require_graph_paths: bool = True
) -> dict[str, object]:
    versions = evidence.get("versions")
    if not isinstance(versions, Mapping) or versions.get("graph_version") != V2_GRAPH_VERSION:
        raise ValueError("G4 baseline does not bind the frozen v2 graph version")
    enrichment = evidence.get("candidate_enrichment")
    if not isinstance(enrichment, Mapping) or any(
        enrichment.get(field) is not True for field in REQUIRED_CANDIDATE_ENRICHMENT
    ):
        raise ValueError("G4 baseline does not prove the v2 candidate enrichment")
    coverage = evidence.get("graph_path_coverage")
    if not isinstance(coverage, Mapping):
        raise ValueError("G4 baseline has no v2 graph path coverage receipt")
    graph_scored = coverage.get("graph_scored_candidates")
    covered = coverage.get("covered_candidates")
    reference_count = coverage.get("routeable_path_reference_count")
    if (
        isinstance(graph_scored, bool)
        or not isinstance(graph_scored, int)
        or isinstance(covered, bool)
        or not isinstance(covered, int)
        or graph_scored != covered
        or coverage.get("coverage_ratio") != 1.0
        or coverage.get("graph_version") != V2_GRAPH_VERSION
        or isinstance(reference_count, bool)
        or not isinstance(reference_count, int)
    ):
        raise ValueError("G4 baseline does not prove 100% routeable v2 path coverage")
    if require_graph_paths and (graph_scored < 1 or reference_count < 1):
        raise ValueError("G4 baseline contains no Graph-scored routeable path")
    safety = evidence.get("safety")
    if not isinstance(safety, Mapping) or int(safety.get("deepseek_requests", -1)) != 0:
        raise ValueError("G4 baseline does not prove zero DeepSeek requests")
    return dict(coverage)


__all__ = [
    "REQUIRED_CANDIDATE_ENRICHMENT",
    "V2_GRAPH_EVIDENCE_PRECONDITION",
    "V2_GRAPH_VERSION",
    "V2_GRAPH_ZERO_LLM_PRECONDITION",
    "validate_v2_http_items",
    "validate_v2_ranked_candidates",
    "validate_v2_readonly_evidence",
]
