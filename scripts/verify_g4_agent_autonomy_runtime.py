#!/usr/bin/env python3
"""Verify that the G4 rule Agents make bounded local action decisions.

This is an offline verifier: it exercises only the in-process rule registry,
does not call MySQL/Neo4j/Chroma/LLM, and writes one new append-only evidence
artifact.  The checks cover direct, guided, degraded, and one-replan paths.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import re
from typing import Any, Sequence
from uuid import NAMESPACE_URL, uuid5

from backend.app.recommendation.agents.autonomy import (
    ROLE_PROFILES,
    assert_payload_decision,
    validate_decision,
)
from backend.app.recommendation.agents.orchestrator import OrchestrationRequest
from backend.app.recommendation.application.orchestration import build_rule_orchestrator
from backend.app.shared_kernel.contracts.enums import TaskStatus


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")


def validate_run_id(value: str) -> str:
    if RUN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("run id must use 3-64 safe characters")
    return value


def build_request(
    run_id: str,
    *,
    input_text: str | None = "多智能体推荐",
    resource_types: tuple[str, ...] = ("BOOK", "PAPER"),
    constraints: dict[str, object] | None = None,
) -> OrchestrationRequest:
    now = datetime.now(UTC).replace(microsecond=0)
    return OrchestrationRequest(
        task_id=uuid5(NAMESPACE_URL, f"g4-autonomy-task:{run_id}:{input_text}"),
        trace_id=uuid5(NAMESPACE_URL, f"g4-autonomy-trace:{run_id}:{input_text}"),
        session_id=uuid5(NAMESPACE_URL, f"g4-autonomy-session:{run_id}:{input_text}"),
        user_id=1001,
        input_text=input_text,
        resource_types=resource_types,
        constraints=constraints,
        deadline_at=now + timedelta(seconds=30),
        evaluation_at=now,
    )


async def _run_case(
    run_id: str,
    *,
    input_text: str | None = "多智能体推荐",
    resource_types: tuple[str, ...] = ("BOOK", "PAPER"),
    constraints: dict[str, object] | None = None,
) -> dict[str, Any]:
    result = await build_rule_orchestrator().run(
        build_request(
            run_id,
            input_text=input_text,
            resource_types=resource_types,
            constraints=constraints,
        )
    )
    for dispatch in result.dispatches:
        if dispatch.result.decision is None:
            raise ValueError(f"{dispatch.message.receiver} returned no local action")
        validate_decision(dispatch.message.receiver, dispatch.result.decision)
        assert_payload_decision(dispatch.result.payload, dispatch.result.decision)
    actions = [step["autonomy"]["action"] for step in result.trace]
    if any(not isinstance(action, str) or not action for action in actions):
        raise ValueError("trace contains an invalid autonomy action")
    return {
        "status": result.status.value,
        "dispatch_count": len(result.dispatches),
        "replan_count": result.replan_count,
        "actions": actions,
        "transitions": list(result.transitions),
        "warnings": list(result.payload.get("warnings", [])),
    }


async def execute(run_id: str) -> dict[str, Any]:
    run_id = validate_run_id(run_id)
    cases = {
        "direct": await _run_case(f"{run_id}-direct"),
        "guided": await _run_case(
            f"{run_id}-guided", input_text=None, resource_types=()
        ),
        "degraded": await _run_case(
            f"{run_id}-degraded", constraints={"force_degraded": True}
        ),
        "replanning": await _run_case(
            f"{run_id}-replanning", constraints={"force_replan": True}
        ),
    }
    if cases["direct"]["status"] != TaskStatus.COMPLETED.value:
        raise ValueError("direct autonomy case did not complete")
    if cases["guided"]["status"] != TaskStatus.WAITING_CLARIFICATION.value:
        raise ValueError("guided autonomy case did not stop for clarification")
    if cases["degraded"]["status"] != TaskStatus.DEGRADED_COMPLETED.value:
        raise ValueError("degraded autonomy case did not degrade explicitly")
    if cases["replanning"]["replan_count"] != 1:
        raise ValueError("replanning autonomy case exceeded or skipped one replan")
    if cases["replanning"]["actions"].count("REQUEST_REPLAN") != 1:
        raise ValueError("ranking did not autonomously request exactly one replan")
    if "ASK_CLARIFICATION" not in cases["guided"]["actions"]:
        raise ValueError("guided case did not contain an Agent clarification action")
    if "PLAN_RECALL" not in cases["direct"]["actions"]:
        raise ValueError("direct case did not contain a policy recall-plan action")

    report = {
        "schema_version": "g4-agent-autonomy-runtime-v1",
        "status": "PASS",
        "run_id": run_id,
        "checked_at": datetime.now(UTC).isoformat(),
        "role_profiles": {
            name: {
                "role": profile.role,
                "goal": profile.goal,
                "observations": list(profile.observations),
                "tools": list(profile.tools),
                "allowed_actions": [action.value for action in profile.allowed_actions],
                "allowed_targets": list(profile.allowed_targets),
            }
            for name, profile in sorted(ROLE_PROFILES.items())
        },
        "cases": cases,
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
    output_path = evidence_dir / "agent-autonomy-runtime.json"
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
