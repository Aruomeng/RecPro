from __future__ import annotations

import unittest

from scripts.build_g4_clarification_plan import WAITING_DELTAS, canonical, request_payload, sha256_bytes
from scripts.execute_g4_clarification_plan import (
    load_request_payload,
    validate_post_counts,
    validate_pre_counts,
)


def _plan() -> dict[str, object]:
    targets = []
    before = 100
    for table, delta in WAITING_DELTAS:
        targets.append(
            {
                "kind": "MYSQL",
                "identifier": f"recpro.recpro.{table}",
                "operation": "APPEND",
                "expected_before_count": before,
                "expected_after_min_count": before + delta,
            }
        )
        before += 1
    run_id = "clarification-executor-test"
    payload = request_payload(run_id, user_id=1001)
    return {
        "idempotency_key": payload["request_id"],
        "input_hashes": {"request_payload": sha256_bytes(canonical(payload))},
        "targets": targets,
    }


class G4ClarificationExecutorTests(unittest.TestCase):
    def test_reconstructs_exact_request_identity(self) -> None:
        plan = _plan()
        payload = load_request_payload(
            plan, request_run_id="clarification-executor-test", user_id=1001
        )
        self.assertEqual(plan["idempotency_key"], payload["request_id"])
        self.assertEqual("HOME", payload["scene"])
        self.assertEqual([], payload["resource_types"])

    def test_preflight_and_postflight_require_exact_19_row_delta(self) -> None:
        plan = _plan()
        before = {
            str(target["identifier"]).rsplit(".", 1)[-1]: int(
                target["expected_before_count"]
            )
            for target in plan["targets"]
        }
        validate_pre_counts(plan, before)
        after = dict(before)
        for target in plan["targets"]:
            table = str(target["identifier"]).rsplit(".", 1)[-1]
            after[table] += int(target["expected_after_min_count"]) - int(
                target["expected_before_count"]
            )
        deltas = validate_post_counts(plan, before, after)
        self.assertEqual(19, sum(deltas.values()))
        self.assertEqual(4, deltas["recommendation_task_transition"])

    def test_postflight_rejects_unplanned_table_change(self) -> None:
        plan = _plan()
        before = {
            str(target["identifier"]).rsplit(".", 1)[-1]: int(
                target["expected_before_count"]
            )
            for target in plan["targets"]
        }
        before["resource_catalog"] = 14989
        after = dict(before)
        after["resource_catalog"] += 1
        with self.assertRaisesRegex(RuntimeError, "unplanned table"):
            validate_post_counts(plan, before, after)


if __name__ == "__main__":
    unittest.main()
