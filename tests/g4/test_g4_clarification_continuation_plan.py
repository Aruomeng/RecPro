from __future__ import annotations

import unittest
from unittest.mock import patch

from scripts.build_g4_clarification_continuation_plan import (
    MAX_CONTINUATION_APPEND_ROWS,
    build_plan,
)


def _evidence(*, candidate_count: int = 6, dispatch_count: int = 7) -> dict[str, object]:
    deltas = {
        "recommendation_agent_artifact": 1,
        "recommendation_agent_message": dispatch_count,
        "recommendation_agent_result": dispatch_count,
        "recommendation_candidate": candidate_count,
        "recommendation_clarification": 1,
        "recommendation_item": candidate_count,
        "recommendation_item_explanation": candidate_count,
        "recommendation_orchestration_result": 1,
        "recommendation_policy_decision": 1,
        "recommendation_record": 1,
        "recommendation_task_context": 1,
        "recommendation_task_transition": 8,
        "recommendation_trace_revision": 1,
    }
    counts = {table: 100 for table in deltas}
    return {
        "schema_version": "g4-clarification-continuation-readonly-evidence-v1",
        "status": "PASS",
        "compose_project": "recpro-test",
        "task_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "trace_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "user_id": 1001,
        "previous_context_version": 1,
        "next_context_version": 2,
        "answers": {"resource_types": "BOOK_AND_PAPER", "topic": "多智能体"},
        "proposed_idempotency_key": "continuation-test-key",
        "orchestration_status": "COMPLETED",
        "candidate_count": candidate_count,
        "item_count": candidate_count,
        "before_counts": counts,
        "after_counts": dict(counts),
        "expected_deltas": deltas,
        "safety": {
            "mysql_writes": 0,
            "neo4j_writes": 0,
            "chroma_writes": 0,
            "external_requests": 0,
            "actual_delete_count": 0,
            "files_deleted": 0,
            "overwritten_inputs": 0,
        },
    }


class G4ClarificationContinuationPlanTests(unittest.TestCase):
    def test_plan_uses_evidence_delta_instead_of_stale_fixed_total(self) -> None:
        evidence = _evidence(candidate_count=6, dispatch_count=7)
        expected_rows = sum(int(value) for value in evidence["expected_deltas"].values())
        self.assertEqual(47, expected_rows)
        with patch(
            "scripts.build_g4_clarification_continuation_plan.load_evidence",
            return_value=(evidence, b"evidence"),
        ), patch(
            "scripts.build_g4_clarification_continuation_plan.current_git_commit",
            return_value="a" * 40,
        ):
            plan = build_plan(
                run_id="continuation-plan-dynamic-test",
                evidence_path=None,
            )
        self.assertEqual(expected_rows, plan["max_changes"])
        self.assertLessEqual(plan["max_changes"], MAX_CONTINUATION_APPEND_ROWS)
        self.assertEqual(
            expected_rows,
            sum(
                int(target["expected_after_min_count"])
                - int(target["expected_before_count"])
                for target in plan["targets"]
            ),
        )

    def test_oversized_evidence_is_rejected(self) -> None:
        evidence = _evidence(candidate_count=6, dispatch_count=7)
        evidence["expected_deltas"]["recommendation_candidate"] = MAX_CONTINUATION_APPEND_ROWS
        with patch(
            "scripts.build_g4_clarification_continuation_plan.load_evidence",
            return_value=(evidence, b"evidence"),
        ):
            with self.assertRaisesRegex(ValueError, "bounded row budget"):
                build_plan(run_id="continuation-plan-budget-test", evidence_path=None)


if __name__ == "__main__":
    unittest.main()
