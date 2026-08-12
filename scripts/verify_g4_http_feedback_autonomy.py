#!/usr/bin/env python3
"""Verify G4 HTTP and G5 interaction Agent actions without a data plane.

The verifier uses the deterministic in-process orchestrator and the pure HTTP
projection plus FeedbackLearningAgent policy.  It does not construct a DB,
Neo4j, Chroma, Worker, or LLM client; the artifact is therefore a contract and
boundary proof, not a claim that the default HTTP runtime is enabled.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime, timedelta
from dataclasses import replace
import json
from pathlib import Path
import re
from typing import Any, Sequence
from uuid import NAMESPACE_URL, uuid5

from backend.app.api.recommendation import RecommendationExecutionResponse
from backend.app.feedback.application.autonomy import (
    FeedbackLearningAgent,
    FeedbackLearningObservation,
)
from backend.app.recommendation.agents.orchestrator import OrchestrationRequest
from backend.app.recommendation.application.g4_projection import (
    G4ProjectionVersions,
    G4ResourceProjection,
    build_http_execution_payload,
)
from backend.app.recommendation.application.orchestration import build_rule_orchestrator
from backend.app.shared_kernel.contracts.autonomy import validate_decision_dict


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")


def validate_run_id(value: str) -> str:
    if RUN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("run id must use 3-64 safe characters")
    return value


async def _build_g4_http_case(run_id: str) -> dict[str, Any]:
    now = datetime.now(UTC).replace(microsecond=0)
    result = await build_rule_orchestrator().run(
        OrchestrationRequest(
            task_id=uuid5(NAMESPACE_URL, f"g4-http-autonomy-task:{run_id}"),
            trace_id=uuid5(NAMESPACE_URL, f"g4-http-autonomy-trace:{run_id}"),
            session_id=uuid5(NAMESPACE_URL, f"g4-http-autonomy-session:{run_id}"),
            user_id=1001,
            input_text="多智能体推荐",
            resource_types=("BOOK", "PAPER"),
            limit=5,
            deadline_at=now + timedelta(seconds=30),
            evaluation_at=now,
        )
    )
    items = [
        {**item, "evidence_confidence": 0.8}
        for item in result.payload["items"]
    ]
    result = replace(result, payload={**result.payload, "items": items})
    resources = {
        int(item["resource_id"]): G4ResourceProjection(
            resource_id=int(item["resource_id"]),
            resource_type="BOOK",
            title=f"Synthetic book {item['resource_id']}",
            authors=("Research author",),
            publication_year=2025,
            availability_status="AVAILABLE_BORROW",
        )
        for item in items
    }
    item_ids = {
        resource_id: 10000 + offset
        for offset, resource_id in enumerate(sorted(resources), start=1)
    }
    payload = build_http_execution_payload(
        result,
        resources=resources,
        versions=G4ProjectionVersions(
            config_bundle="rec-1.0.0",
            dataset="lib-books-v1",
            graph="lib-books-v1-20260810",
            embedding="hash-char-ngram-v1",
        ),
        evaluation_at=now,
        record_id=9001,
        item_ids=item_ids,
    )
    response = RecommendationExecutionResponse.model_validate(payload)
    for action in payload["agent_actions"]:
        validate_decision_dict(action["agent_name"], action)
    return {
        "status": response.status.value,
        "agent_action_count": len(response.agent_actions),
        "actions": [
            {
                "step_no": action.step_no,
                "agent_name": action.agent_name,
                "action": action.action.value,
                "target": action.target,
                "reason_code": action.reason_code,
            }
            for action in response.agent_actions
        ],
        "external_http_calls": 0,
    }


def _build_feedback_cases() -> dict[str, dict[str, Any]]:
    agent = FeedbackLearningAgent()
    observations = {
        "pending_negative": FeedbackLearningObservation(
            event_type="NOT_INTERESTED",
            replayed=False,
            profile_update_pending=True,
            state_type="HIDDEN",
        ),
        "idempotent_replay": FeedbackLearningObservation(
            event_type="NOT_INTERESTED",
            replayed=True,
            profile_update_pending=True,
            state_type="HIDDEN",
        ),
        "no_delta": FeedbackLearningObservation(
            event_type="RECOMMENDATION_IMPRESSION",
            replayed=False,
            profile_update_pending=False,
        ),
    }
    cases: dict[str, dict[str, Any]] = {}
    for name, observation in observations.items():
        public = agent.public_decision(observation)
        validate_decision_dict(agent.name, public)
        cases[name] = {
            "action": public["action"],
            "target": public["target"],
            "reason_code": public["reason_code"],
            "parameters": public["parameters"],
        }
    if cases["pending_negative"]["action"] != "PROPOSE_PROFILE_DELTA":
        raise ValueError("pending feedback did not propose a profile delta")
    if cases["idempotent_replay"]["action"] != "RETURN_RESULT":
        raise ValueError("feedback replay proposed a second action")
    if cases["no_delta"]["action"] != "RETURN_RESULT":
        raise ValueError("impression no-op did not return safely")
    return cases


async def execute(run_id: str) -> dict[str, Any]:
    run_id = validate_run_id(run_id)
    report = {
        "schema_version": "g4-http-feedback-autonomy-v1",
        "status": "PASS",
        "run_id": run_id,
        "checked_at": datetime.now(UTC).isoformat(),
        "g4_http_projection": await _build_g4_http_case(f"{run_id}-g4"),
        "g5_feedback_boundary": _build_feedback_cases(),
        "safety": {
            "external_llm_requests": 0,
            "database_reads": 0,
            "database_writes": 0,
            "neo4j_reads": 0,
            "neo4j_writes": 0,
            "chroma_reads": 0,
            "chroma_writes": 0,
            "outbox_claims": 0,
            "files_deleted": 0,
            "database_physical_deletions": 0,
            "artifact_overwrites": 0,
        },
    }
    evidence_dir = PROJECT_ROOT / "artifacts" / "verification" / "g4" / run_id
    evidence_dir.mkdir(parents=True, exist_ok=False)
    output_path = evidence_dir / "http-feedback-autonomy.json"
    with output_path.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    report["artifact_path"] = output_path.relative_to(PROJECT_ROOT).as_posix()
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = asyncio.run(execute(args.run_id))
    except (OSError, ValueError, RuntimeError, TypeError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "FAIL", "error": type(exc).__name__}, ensure_ascii=False))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
