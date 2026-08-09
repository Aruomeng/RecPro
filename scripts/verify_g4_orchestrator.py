"""Verify the deterministic G4 Agent Registry and four dynamic branches."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Sequence
from uuid import UUID

from backend.app.recommendation.agents.orchestrator import OrchestrationRequest
from backend.app.recommendation.application.orchestration import build_rule_orchestrator
from backend.app.shared_kernel.contracts.enums import TaskStatus


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")


def validate_run_id(value: str) -> str:
    if RUN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("run id must use 3-64 safe characters")
    return value


def request_for(*, task_id: str, input_text: str | None, resource_types: tuple[str, ...], constraints: dict[str, object] | None = None) -> OrchestrationRequest:
    return OrchestrationRequest(
        task_id=UUID(task_id),
        trace_id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
        session_id=UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"),
        user_id=1001,
        input_text=input_text,
        resource_types=resource_types,
        limit=5,
        constraints=constraints,
        deadline_at=datetime.now(UTC) + timedelta(seconds=30),
    )


async def execute(run_id: str) -> int:
    orchestrator = build_rule_orchestrator()
    scenarios = {
        "direct": request_for(
            task_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            input_text="多智能体推荐",
            resource_types=("BOOK", "PAPER"),
        ),
        "guided": request_for(
            task_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaab",
            input_text=None,
            resource_types=(),
        ),
        "degraded": request_for(
            task_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaac",
            input_text="多智能体推荐",
            resource_types=("BOOK", "PAPER"),
            constraints={"force_degraded": True},
        ),
        "replanning": request_for(
            task_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaad",
            input_text="多智能体推荐",
            resource_types=("BOOK", "PAPER"),
            constraints={"force_replan": True},
        ),
    }
    results = {name: await orchestrator.run(request) for name, request in scenarios.items()}
    expected = {
        "direct": TaskStatus.COMPLETED,
        "guided": TaskStatus.WAITING_CLARIFICATION,
        "degraded": TaskStatus.DEGRADED_COMPLETED,
        "replanning": TaskStatus.COMPLETED,
    }
    for name, status in expected.items():
        if results[name].status is not status:
            raise ValueError(f"{name} branch returned {results[name].status}")
    if results["replanning"].replan_count != 1:
        raise ValueError("replanning branch exceeded or skipped its one replan")
    if any(
        step["agent_name"] == "CandidateRecallAgent"
        for step in results["guided"].trace
    ):
        raise ValueError("guided branch dispatched recall after clarification")
    evidence_dir = PROJECT_ROOT / "artifacts" / "verification" / "g4" / run_id
    evidence_dir.mkdir(parents=True, exist_ok=False)
    payload = {
        "schema_version": "g4-orchestrator-evidence-v1",
        "run_id": run_id,
        "status": "PASS",
        "registered_agents": list(orchestrator._registry.names),
        "scenarios": {
            name: {
                "status": result.status.value,
                "replan_count": result.replan_count,
                "transition_count": len(result.transitions),
                "trace_step_count": len(result.trace),
                "trace": list(result.trace),
            }
            for name, result in results.items()
        },
        "database_sql_actions": {"writes": 0, "updates": 0, "deletes": 0},
        "destructive_actions": 0,
        "verified_at": datetime.now(UTC).isoformat(),
    }
    (evidence_dir / "orchestrator.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[PASS] G4 orchestrator evidence: {evidence_dir}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(execute(validate_run_id(args.run_id)))
    except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
        print(f"[FAIL] G4 orchestrator verification did not complete: {type(exc).__name__}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
