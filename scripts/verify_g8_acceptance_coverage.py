#!/usr/bin/env python3
"""Audit offline coverage for the frozen A01--A25 acceptance matrix.

This command is an evidence *index*, not an acceptance-runner.  It reads the
matrix, source/tests, and already-existing verification artifacts only.  It
does not start a service, connect to MySQL/Neo4j/Chroma, call an external
provider, claim an Outbox row, or modify existing evidence.  Every run gets a
new directory and fails if that directory already exists.

The report deliberately keeps two questions separate:

* ``offline_assessment`` says whether the repository currently has a direct
  test, only related coverage, or no direct test for the frozen behavior.
* ``final_revalidation`` remains ``PENDING`` until the A01--A25 G8/G9 runtime
  protocol is executed with its own frozen data and evidence.

This separation prevents a static/unit-test inventory from being mistaken for
the final paper or release acceptance result.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Iterable, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
MATRIX_ROW_PATTERN = re.compile(r"^\|\s*(A\d{2})\s*\|(.+)\|\s*$")
TEST_REF_PATTERN = re.compile(r"^(?P<path>[^:]+)::(?P<name>test_[A-Za-z0-9_]+)$")


def validate_run_id(value: str) -> str:
    if RUN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("run id must contain only 3-64 safe characters")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


def resolve_inside_project(value: str | Path, *, label: str) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError(f"{label} must stay inside the repository") from exc
    return resolved


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def parse_acceptance_matrix(path: Path) -> list[dict[str, str]]:
    """Parse only the frozen A01--A25 table, rejecting drift or duplicates."""

    rows: dict[str, dict[str, str]] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        match = MATRIX_ROW_PATTERN.match(raw_line)
        if not match:
            continue
        case_id, remainder = match.groups()
        cells = [cell.strip() for cell in remainder.split("|")]
        if len(cells) != 4:
            continue
        if case_id in rows:
            raise ValueError(f"duplicate acceptance case in matrix: {case_id}")
        rows[case_id] = {
            "case_id": case_id,
            "semantics": cells[0],
            "first_gate": cells[1],
            "final_gate": cells[2],
            "evidence_type": cells[3],
        }
    expected = [f"A{index:02d}" for index in range(1, 26)]
    if list(sorted(rows)) != expected:
        missing = sorted(set(expected) - set(rows))
        extra = sorted(set(rows) - set(expected))
        raise ValueError(f"acceptance matrix must contain A01-A25 exactly; missing={missing}, extra={extra}")
    return [rows[item] for item in expected]


# These references are intentionally explicit.  A missing function/path makes
# the mapping stale instead of silently lowering the audit quality.
CASE_COVERAGE: Mapping[str, dict[str, Any]] = {
    "A01": {
        "offline_assessment": "RELATED",
        "assessment_reason": "Replay ordering is tested, but the frozen final profile content-hash assertion is not a dedicated test.",
        "test_refs": ["tests/g2/test_profile_replay.py::test_replay_is_deterministic_under_input_reordering"],
        "source_refs": ["backend/app/profile/replay.py"],
        "tool_refs": ["scripts/replay_g2_profile.py", "scripts/verify_g5_audit_replay_runtime.py"],
        "artifact_globs": ["artifacts/verification/g2/*/runtime.json", "artifacts/verification/g5/g5-audit-replay-*/runtime.json"],
    },
    "A02": {
        "offline_assessment": "RELATED",
        "assessment_reason": "HTTP idempotency and task identity are tested; a persisted recommendation-record count assertion is not in the unit suite.",
        "test_refs": ["tests/g3/test_recommendation_api.py::test_create_and_replay_are_explicit_and_user_scoped"],
        "source_refs": ["backend/app/api/recommendation.py"],
        "tool_refs": ["scripts/verify_g3_api_runtime.py"],
        "artifact_globs": ["artifacts/verification/g3/g3-api-runtime-*/api-runtime.json"],
    },
    "A03": {
        "offline_assessment": "RELATED",
        "assessment_reason": "Direct behavior UUID validation exists and the runtime verifier covers related replay paths, but a dedicated event-fact uniqueness assertion is absent from the offline suite.",
        "test_refs": ["tests/g5/test_feedback_api.py::test_behavior_accepts_direct_events_and_rejects_derived_events"],
        "source_refs": ["backend/app/feedback/application/service.py", "backend/app/profile/adapters/behavior_mysql.py"],
        "tool_refs": ["scripts/verify_g5_feedback_runtime.py"],
        "artifact_globs": ["artifacts/verification/g5/g5-feedback-*/g5-runtime.json", "artifacts/verification/g5/g5-http-*/http-runtime.json"],
    },
    "A04": {
        "offline_assessment": "DIRECT",
        "assessment_reason": "Feedback UUID replay is asserted at the API boundary and in the G5 runtime verifier; final G8 replay still remains pending.",
        "test_refs": ["tests/g5/test_feedback_api.py::test_feedback_returns_pending_then_replayed"],
        "source_refs": ["backend/app/feedback/application/service.py", "backend/app/api/feedback.py"],
        "tool_refs": ["scripts/verify_g5_feedback_runtime.py", "scripts/verify_g5_http_runtime.py"],
        "artifact_globs": ["artifacts/verification/g5/g5-feedback-*/g5-runtime.json", "artifacts/verification/g5/g5-http-*/http-runtime.json"],
    },
    "A05": {
        "offline_assessment": "DIRECT",
        "assessment_reason": "The orchestrator test asserts GUIDED and stops before recall for an unclear request.",
        "test_refs": ["tests/g4/test_orchestrator.py::test_unclear_path_stops_at_guided_before_recall"],
        "source_refs": ["backend/app/recommendation/agents/orchestrator.py", "backend/app/recommendation/agents/rule_agents.py"],
        "tool_refs": ["scripts/verify_g4_orchestrator.py"],
        "artifact_globs": ["artifacts/verification/g4/g4-orchestrator-*/orchestrator.json"],
    },
    "A06": {
        "offline_assessment": "DIRECT",
        "assessment_reason": "Explicit topic and paper intent are asserted by the recommendation service tests.",
        "test_refs": ["tests/g3/test_recommendation_service.py::test_intent_preserves_explicit_topic_and_type", "tests/g4/test_llm_intent_agent.py::test_provider_is_opt_in_and_only_classifies"],
        "source_refs": ["backend/app/recommendation/application/intent.py", "backend/app/recommendation/agents/llm_agents.py"],
        "tool_refs": ["scripts/verify_g3_runtime.py", "scripts/verify_g4_orchestrator.py"],
        "artifact_globs": ["artifacts/verification/g3/g3-runtime-*/runtime.json", "artifacts/verification/g4/g4-orchestrator-*/orchestrator.json"],
    },
    "A07": {
        "offline_assessment": "DIRECT",
        "assessment_reason": "The feedback application marks the target resource READ while deterministic profile replay retains the topic interest and creates no topic-negative signal.",
        "test_refs": ["tests/g5/test_feedback_application.py::test_already_read_marks_only_the_target_resource_state", "tests/g2/test_profile_replay.py::test_already_read_preserves_topic_interest_without_creating_topic_negative"],
        "source_refs": ["backend/app/feedback/application/service.py", "backend/app/profile/replay.py"],
        "tool_refs": [],
        "artifact_globs": ["artifacts/verification/g5/g5-feedback-*/g5-runtime.json"],
    },
    "A08": {
        "offline_assessment": "RELATED",
        "assessment_reason": "Topic-negative penalty and bounded score behavior are tested; the strict counterfactual decrease is not a dedicated assertion.",
        "test_refs": ["tests/g3/test_recommendation_service.py::test_topic_negative_penalty_is_bounded_and_explanation_is_template", "tests/g2/test_profile_replay.py::test_as_of_boundary_excludes_future_facts_and_maps_only_topic_negative"],
        "source_refs": ["backend/app/recommendation/application/public.py", "backend/app/profile/replay.py"],
        "tool_refs": ["scripts/verify_g5_feedback_runtime.py"],
        "artifact_globs": ["artifacts/verification/g5/g5-feedback-*/g5-runtime.json"],
    },
    "A09": {
        "offline_assessment": "RELATED",
        "assessment_reason": "Exposure fields and the valid-exposure path exist; a below-0.5 negative boundary test is still missing.",
        "test_refs": ["tests/g5/test_feedback_application.py::test_impression_and_behavior_commit_as_one_batch", "tests/g5/test_feedback_api.py::test_impression_batch_is_user_scoped_and_item_idempotent"],
        "source_refs": ["backend/app/feedback/adapters/mysql.py", "backend/app/feedback/domain/models.py"],
        "tool_refs": ["scripts/verify_g5_http_runtime.py"],
        "artifact_globs": ["artifacts/verification/g5/g5-http-*/http-runtime.json", "artifacts/verification/g7/g7-frontend-browser-mysql-readonly-*/readonly.json"],
    },
    "A10": {
        "offline_assessment": "RELATED",
        "assessment_reason": "The 1000ms threshold is implemented and a valid exposure is tested; the below-1000ms negative boundary is not directly asserted.",
        "test_refs": ["tests/g5/test_feedback_application.py::test_impression_and_behavior_commit_as_one_batch"],
        "source_refs": ["backend/app/feedback/adapters/mysql.py", "backend/app/feedback/domain/models.py"],
        "tool_refs": ["scripts/verify_g5_http_runtime.py"],
        "artifact_globs": ["artifacts/verification/g5/g5-http-*/http-runtime.json", "artifacts/verification/g7/g7-frontend-browser-mysql-readonly-*/readonly.json"],
    },
    "A11": {
        "offline_assessment": "RELATED",
        "assessment_reason": "Vector/Chroma failure fallback is tested; the final candidate field semantic_score=null contract is not separately asserted.",
        "test_refs": ["tests/g6/test_retrieval_fusion.py::test_vector_failure_is_bounded_and_falls_back_to_mysql", "tests/g6/test_vector_recall.py::test_reader_fails_closed_on_store_error_and_malformed_metadata"],
        "source_refs": ["backend/app/catalog/adapters/chroma.py", "backend/app/recommendation/application/orchestration.py"],
        "tool_refs": ["scripts/verify_g6_readonly_fusion.py"],
        "artifact_globs": ["artifacts/verification/g6/g6-retrieval-fusion-readonly-*/readonly.json"],
    },
    "A12": {
        "offline_assessment": "DIRECT",
        "assessment_reason": "A graph timeout is retried within the bounded budget, emits an unavailable dependency warning, sets kg_score=null, and leaves explanation evidence refs free of an invented graph path.",
        "test_refs": ["tests/g6/test_retrieval_fusion.py::test_graph_timeout_is_null_and_explanation_cannot_invent_graph_path"],
        "source_refs": ["backend/app/catalog/adapters/neo4j.py", "backend/app/recommendation/application/orchestration.py"],
        "tool_refs": ["scripts/verify_g6_readonly_fusion.py"],
        "artifact_globs": ["artifacts/verification/g6/g6-retrieval-fusion-readonly-*/readonly.json"],
    },
    "A13": {
        "offline_assessment": "RELATED",
        "assessment_reason": "MySQL fallback when an optional channel fails is covered; simultaneous Graph+Vector outage with sufficient MySQL candidates is not isolated.",
        "test_refs": ["tests/g6/test_retrieval_fusion.py::test_vector_failure_is_bounded_and_falls_back_to_mysql"],
        "source_refs": ["backend/app/recommendation/application/orchestration.py", "backend/app/catalog/application/public.py"],
        "tool_refs": ["scripts/verify_g6_readonly_fusion.py"],
        "artifact_globs": ["artifacts/verification/g6/g6-retrieval-fusion-readonly-*/readonly.json"],
    },
    "A14": {
        "offline_assessment": "DIRECT",
        "assessment_reason": "API and health tests assert MySQL-unavailable fail-closed behavior and no service dispatch.",
        "test_refs": ["tests/g3/test_recommendation_api.py::test_pipeline_flag_fails_closed", "tests/g1/backend/test_health_api.py::test_unavailable_mysql_uses_uniform_error_response"],
        "source_refs": ["backend/app/api/recommendation.py", "backend/app/main.py"],
        "tool_refs": ["scripts/verify_g3_api_runtime.py", "scripts/verify_g1_runtime.py"],
        "artifact_globs": ["artifacts/verification/g3/g3-api-runtime-*/api-runtime.json", "artifacts/verification/g1/g1-runtime-*/runtime-verification.json"],
    },
    "A15": {
        "offline_assessment": "RELATED",
        "assessment_reason": "Bounded score and finite configuration contracts exist, but there is no parameterized missing-feature score matrix for every optional feature.",
        "test_refs": ["tests/g3/test_recommendation_service.py::test_topic_negative_penalty_is_bounded_and_explanation_is_template", "tests/contracts/test_contract_schemas.py::test_non_finite_numbers_are_rejected_by_shared_semantics"],
        "source_refs": ["backend/app/recommendation/application/public.py", "backend/app/recommendation/ranking/service.py"],
        "tool_refs": ["scripts/verify_g3_runtime.py"],
        "artifact_globs": ["artifacts/verification/g3/g3-runtime-*/runtime.json"],
    },
    "A16": {
        "offline_assessment": "RELATED",
        "assessment_reason": "Deterministic ranking and frozen evaluation_at fixtures are tested; a complete snapshot/version/seed/evaluation_at replay hash is not yet one test.",
        "test_refs": ["tests/g3/test_recommendation_service.py::test_recommendation_is_deterministic_and_has_evidence", "tests/g4/test_persistent_orchestration.py::test_trace_artifact_is_content_addressed_and_replay_stable"],
        "source_refs": ["backend/app/recommendation/application/public.py", "backend/app/recommendation/application/persistent_orchestration.py"],
        "tool_refs": ["scripts/verify_experiment_freeze.py", "scripts/verify_g5_audit_replay_runtime.py"],
        "artifact_globs": ["artifacts/verification/experiment/*/freeze-preflight.json", "artifacts/verification/g5/g5-audit-replay-*/runtime.json"],
    },
    "A17": {
        "offline_assessment": "DIRECT",
        "assessment_reason": "Ranking tests assert author/topic caps for sufficient candidates and mark deferred items diversity_relaxed when coverage is insufficient.",
        "test_refs": ["tests/g3/test_ranking_service.py::test_author_and_topic_caps_are_respected_when_candidates_are_sufficient", "tests/g3/test_ranking_service.py::test_insufficient_candidates_mark_diversity_relaxed_instead_of_faking_diversity"],
        "source_refs": ["backend/app/recommendation/ranking/service.py", "backend/app/recommendation/application/public.py"],
        "tool_refs": [],
        "artifact_globs": ["artifacts/verification/g3/g3-runtime-*/runtime.json"],
    },
    "A18": {
        "offline_assessment": "RELATED",
        "assessment_reason": "DEGRADED delivery is tested for optional-channel loss; the single-difficulty-level reading-path case is not isolated.",
        "test_refs": ["tests/g4/test_orchestrator.py::test_degraded_path_preserves_results_and_warnings"],
        "source_refs": ["backend/app/recommendation/agents/orchestrator.py", "backend/app/recommendation/agents/rule_agents.py"],
        "tool_refs": ["scripts/verify_g4_orchestrator.py"],
        "artifact_globs": ["artifacts/verification/g4/g4-orchestrator-*/orchestrator.json"],
    },
    "A19": {
        "offline_assessment": "RELATED",
        "assessment_reason": "Evidence omission fails closed and mock explanations are evidence-bounded; no fault-injecting invented-fact provider test is present.",
        "test_refs": ["tests/g4/test_g4_projection.py::test_projection_fails_closed_when_agent_omits_evidence_confidence", "tests/g1/backend/test_mock_llm.py::test_explanation_uses_only_supplied_evidence"],
        "source_refs": ["backend/app/recommendation/explanation/service.py", "backend/app/llm/adapters/mock.py"],
        "tool_refs": ["scripts/verify_g4_recommendation_projection_result.py"],
        "artifact_globs": ["artifacts/verification/g4/g4-projection-apply-*/g4-recommendation-projection-apply.json"],
    },
    "A20": {
        "offline_assessment": "DIRECT",
        "assessment_reason": "Recommendation tests require evidence references for every item and projection tests preserve candidate channels.",
        "test_refs": ["tests/g3/test_recommendation_service.py::test_recommendation_is_deterministic_and_has_evidence", "tests/g4/test_g4_projection.py::test_complete_result_projects_into_the_frozen_http_contract"],
        "source_refs": ["backend/app/recommendation/application/public.py", "backend/app/recommendation/application/g4_projection.py"],
        "tool_refs": ["scripts/verify_g4_recommendation_projection_result.py"],
        "artifact_globs": ["artifacts/verification/g3/g3-runtime-*/runtime.json", "artifacts/verification/g4/g4-projection-apply-*/g4-recommendation-projection-apply.json"],
    },
    "A21": {
        "offline_assessment": "DIRECT",
        "assessment_reason": "The orchestrator test asserts replan_count=1 and the second recall/rank trace.",
        "test_refs": ["tests/g4/test_orchestrator.py::test_replanning_is_bounded_to_one_and_has_distinct_trace"],
        "source_refs": ["backend/app/recommendation/agents/orchestrator.py"],
        "tool_refs": ["scripts/verify_g4_orchestrator.py"],
        "artifact_globs": ["artifacts/verification/g4/g4-orchestrator-*/orchestrator.json"],
    },
    "A22": {
        "offline_assessment": "DIRECT",
        "assessment_reason": "The unclear-path test asserts early stop before CandidateRecallAgent and RankingAgent.",
        "test_refs": ["tests/g4/test_orchestrator.py::test_unclear_path_stops_at_guided_before_recall"],
        "source_refs": ["backend/app/recommendation/agents/orchestrator.py"],
        "tool_refs": ["scripts/verify_g4_orchestrator.py"],
        "artifact_globs": ["artifacts/verification/g4/g4-orchestrator-*/orchestrator.json"],
    },
    "A23": {
        "offline_assessment": "RELATED",
        "assessment_reason": "Feedback-to-Outbox and worker profile projection are tested; a single end-to-end version/change-log assertion is not in the offline suite.",
        "test_refs": ["tests/g5/test_feedback_application.py::test_topic_feedback_appends_profile_outbox_and_resource_state", "tests/g5/test_profile_worker.py::test_worker_commits_profile_and_done_together"],
        "source_refs": ["backend/app/profile/adapters/refresh_mysql.py", "backend/app/feedback/application/service.py"],
        "tool_refs": ["scripts/verify_g5_feedback_runtime.py", "scripts/verify_g5_worker_recovery_runtime.py"],
        "artifact_globs": ["artifacts/verification/g5/g5-feedback-*/g5-runtime.json", "artifacts/verification/g5/g5-worker-recovery-*/runtime.json"],
    },
    "A24": {
        "offline_assessment": "DIRECT",
        "assessment_reason": "The pure policy state machine holds an automatic output type through the minimum two rounds and hysteresis band, while the rule Agent accepts an explicit output type override immediately.",
        "test_refs": ["tests/g4/test_output_type_stability.py::test_near_threshold_sequence_holds_for_two_rounds_then_switches", "tests/g4/test_output_type_stability.py::test_rule_policy_emits_stability_reason_and_accepts_explicit_override"],
        "source_refs": ["backend/app/recommendation/application/intent.py", "backend/app/recommendation/agents/llm_agents.py"],
        "tool_refs": [],
        "artifact_globs": ["artifacts/verification/g4/g4-orchestrator-*/orchestrator.json"],
    },
    "A25": {
        "offline_assessment": "RELATED",
        "assessment_reason": "Historical as_of replay and input-freeze blockers are tested; a complete resource/behavior/state/hotness historical replay comparison is not yet frozen.",
        "test_refs": ["tests/g9/test_experiment_freeze.py::test_current_fixture_is_reproducible_but_not_paper_confirmatory", "tests/g9/test_evaluation_freeze_inputs.py::test_demo_fixture_is_explicitly_blocked_with_all_missing_inputs", "tests/g2/test_profile_replay.py::test_as_of_boundary_excludes_future_facts_and_maps_only_topic_negative"],
        "source_refs": ["backend/app/profile/replay.py", "scripts/verify_experiment_freeze.py"],
        "tool_refs": ["scripts/verify_g5_audit_replay_runtime.py", "scripts/verify_evaluation_freeze_inputs.py"],
        "artifact_globs": ["artifacts/verification/g5/g5-audit-replay-*/runtime.json", "artifacts/verification/experiment-inputs/*/input-freeze-report.json"],
    },
}


def _test_ref_evidence(reference: str) -> dict[str, Any]:
    match = TEST_REF_PATTERN.fullmatch(reference)
    if match is None:
        return {"reference": reference, "valid": False, "reason": "invalid test reference format"}
    path = resolve_inside_project(match.group("path"), label="test reference")
    name = match.group("name")
    if not path.is_file():
        return {"reference": reference, "valid": False, "reason": "test file missing"}
    text = path.read_text(encoding="utf-8")
    function_pattern = re.compile(rf"^\s*(?:async\s+)?def\s+{re.escape(name)}\s*\(", re.MULTILINE)
    found = function_pattern.search(text)
    return {
        "reference": reference,
        "valid": found is not None,
        "path": _relative(path),
        "name": name,
        "line": text.count("\n", 0, found.start()) + 1 if found else None,
        "sha256": sha256_file(path),
        "reason": None if found else "test function missing",
    }


def _path_evidence(reference: str, *, label: str) -> dict[str, Any]:
    path = resolve_inside_project(reference, label=label)
    return {
        "path": _relative(path),
        "exists": path.is_file(),
        "bytes": path.stat().st_size if path.is_file() else None,
        "sha256": sha256_file(path) if path.is_file() else None,
    }


def _artifact_summary(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": _relative(path),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }
    # Only copy non-sensitive, stable status counters from known evidence keys.
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        result["json_readable"] = False
        return result
    result["json_readable"] = isinstance(payload, dict)
    if isinstance(payload, dict):
        for key in (
            "status",
            "schema_version",
            "database_reads",
            "database_writes",
            "neo4j_reads",
            "neo4j_writes",
            "chroma_reads",
            "chroma_writes",
            "external_llm_requests",
            "files_deleted",
            "actual_delete_count",
        ):
            if key in payload and isinstance(payload[key], (str, int, float, bool, type(None))):
                result[key] = payload[key]
    return result


def _matching_artifacts(patterns: Iterable[str]) -> list[dict[str, Any]]:
    paths: dict[str, Path] = {}
    for pattern in patterns:
        # Path.glob handles nested wildcard patterns relative to the project.
        for path in PROJECT_ROOT.glob(pattern):
            if path.is_file() and path.is_relative_to(PROJECT_ROOT):
                paths[_relative(path)] = path
    return [_artifact_summary(paths[key]) for key in sorted(paths)[:12]]


def _case_report(matrix_row: dict[str, str]) -> dict[str, Any]:
    case_id = matrix_row["case_id"]
    mapping = CASE_COVERAGE[case_id]
    tests = [_test_ref_evidence(item) for item in mapping["test_refs"]]
    sources = [_path_evidence(item, label="source reference") for item in mapping["source_refs"]]
    tools = [_path_evidence(item, label="tool reference") for item in mapping["tool_refs"]]
    artifacts = _matching_artifacts(mapping["artifact_globs"])
    mapping_valid = all(item["valid"] for item in tests) and all(item["exists"] for item in sources + tools)
    return {
        **matrix_row,
        "offline_assessment": mapping["offline_assessment"],
        "assessment_reason": mapping["assessment_reason"],
        "mapping_valid": mapping_valid,
        "test_evidence": tests,
        "source_evidence": sources,
        "tool_evidence": tools,
        "runtime_artifacts": artifacts,
        "runtime_artifact_count": len(artifacts),
        "final_revalidation": "PENDING",
    }


def build_coverage_report(*, matrix_path: Path, git_status: str, git_commit: str) -> dict[str, Any]:
    matrix_rows = parse_acceptance_matrix(matrix_path)
    cases = [_case_report(row) for row in matrix_rows]
    stale = [item["case_id"] for item in cases if not item["mapping_valid"]]
    counts = {
        "total": len(cases),
        "direct": sum(item["offline_assessment"] == "DIRECT" for item in cases),
        "related": sum(item["offline_assessment"] == "RELATED" for item in cases),
        "missing": sum(item["offline_assessment"] == "MISSING" for item in cases),
        "mapping_stale": len(stale),
        "runtime_artifact_cases": sum(item["runtime_artifact_count"] > 0 for item in cases),
        "final_revalidation_pending": sum(item["final_revalidation"] == "PENDING" for item in cases),
    }
    blockers: list[dict[str, str]] = []
    if stale:
        blockers.append({"code": "A_MATRIX_MAPPING_STALE", "message": f"Coverage references are stale for: {', '.join(stale)}."})
    blockers.append({"code": "A01_A25_FINAL_REVALIDATION_PENDING", "message": "A01-A25 final G8/G9 runtime revalidation remains pending for every case."})
    for item in cases:
        if item["offline_assessment"] == "MISSING":
            blockers.append({"code": f"{item['case_id']}_DIRECT_TEST_MISSING", "message": item["assessment_reason"]})
    return {
        "schema_version": "g8-acceptance-coverage-audit-v1",
        "status": "PASS_WITH_BLOCKERS",
        "release_candidate_ready": False,
        "verified_at": datetime.now(UTC).isoformat(),
        "git": {
            "commit": git_commit,
            "status_before_report": git_status,
        },
        "matrix": {
            "path": _relative(matrix_path),
            "sha256": sha256_file(matrix_path),
            "case_ids": [item["case_id"] for item in cases],
        },
        "coverage_counts": counts,
        "cases": cases,
        "blockers": blockers,
        "safety": {
            "database_reads": 0,
            "database_writes": 0,
            "neo4j_reads": 0,
            "neo4j_writes": 0,
            "chroma_reads": 0,
            "chroma_writes": 0,
            "external_llm_requests": 0,
            "files_deleted": 0,
            "database_physical_deletes": 0,
            "artifacts_overwritten": 0,
        },
    }


def execute(*, run_id: str, matrix_path: Path) -> dict[str, Any]:
    run_id = validate_run_id(run_id)
    matrix_path = resolve_inside_project(matrix_path, label="acceptance matrix")
    if not matrix_path.is_file():
        raise FileNotFoundError(matrix_path)
    evidence_dir = PROJECT_ROOT / "artifacts" / "verification" / "g8" / run_id
    evidence_dir.mkdir(parents=True, exist_ok=False)
    report = build_coverage_report(
        matrix_path=matrix_path,
        git_status=_git("status", "--porcelain"),
        git_commit=_git("rev-parse", "HEAD"),
    )
    output_path = evidence_dir / "acceptance-coverage.json"
    with output_path.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--matrix", type=Path, default=PROJECT_ROOT / "docs" / "acceptance_matrix.md")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        execute(run_id=args.run_id, matrix_path=args.matrix)
    except Exception as exc:  # pragma: no cover - CLI boundary
        print(f"[FAIL] A01-A25 coverage audit did not complete: {type(exc).__name__}: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
