from __future__ import annotations

import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from scripts.build_g4_clarification_plan import (
    REQUEST_SPEC,
    WAITING_DELTAS,
    build_plan,
    request_payload,
)
from scripts.verify_g4_clarification_readonly import build_request


class G4ClarificationPlanTests(unittest.TestCase):
    def test_readonly_request_preserves_home_empty_shape(self) -> None:
        request = build_request(
            "clarification-readonly-test",
            user_id=1001,
            evaluation_at=datetime(2026, 8, 11, 1, 0, tzinfo=UTC),
        )
        self.assertEqual("HOME", request.scene)
        self.assertIsNone(request.input_text)
        self.assertEqual((), request.resource_types)
        self.assertIsNone(request.output_type)

    def test_request_payload_has_a_new_stable_idempotency_identity(self) -> None:
        first = request_payload("clarification-plan-a", user_id=1001)
        second = request_payload("clarification-plan-a", user_id=1001)
        other = request_payload("clarification-plan-b", user_id=1001)
        self.assertEqual(first, second)
        self.assertNotEqual(first["request_id"], other["request_id"])
        self.assertEqual(REQUEST_SPEC, {key: first[key] for key in REQUEST_SPEC})

    def test_waiting_plan_is_bounded_to_append_only_facts(self) -> None:
        counts = {
            table: 100 + index
            for index, (table, _delta) in enumerate(WAITING_DELTAS)
        }
        counts.update(
            {
                "resource_catalog": 14989,
                "resource_book_detail": 14986,
                "tag_dictionary": 8522,
                "resource_tag": 70762,
                "resource_index_state": 14989,
            }
        )
        evidence = {
            "schema_version": "g4-clarification-readonly-evidence-v1",
            "status": "PASS",
            "compose_project": "recpro-test",
            "query_spec": REQUEST_SPEC,
            "orchestration_status": "WAITING_CLARIFICATION",
            "dispatch_count": 4,
            "transition_count": 4,
            "safety": {
                "mysql_writes": 0,
                "neo4j_writes": 0,
                "chroma_writes": 0,
                "external_requests": 0,
                "actual_delete_count": 0,
                "files_deleted": 0,
                "overwritten_inputs": 0,
            },
            "before_counts": counts,
            "after_counts": counts,
        }
        with patch(
            "scripts.build_g4_clarification_plan.load_evidence",
            return_value=(evidence, b"evidence"),
        ), patch(
            "scripts.build_g4_clarification_plan.git_commit",
            return_value="a" * 40,
        ):
            plan = build_plan(
                run_id="clarification-plan-test",
                evidence_path=None,  # patched loader does not access the path
                user_id=1001,
            )
        self.assertEqual("S1_APPEND", plan["classification"])
        self.assertEqual("DRY_RUN", plan["mode"])
        self.assertEqual(19, plan["max_changes"])
        self.assertTrue(all(target["operation"] == "APPEND" for target in plan["targets"]))
        self.assertNotIn("recommendation_candidate", {
            target["identifier"].rsplit(".", 1)[-1] for target in plan["targets"]
        })
        self.assertEqual(0, plan["safety_assertions"]["file_deletions"])
        self.assertFalse(plan["safety_assertions"]["overwrite_existing"])


if __name__ == "__main__":
    unittest.main()
