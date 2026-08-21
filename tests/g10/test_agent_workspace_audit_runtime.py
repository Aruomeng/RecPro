from __future__ import annotations

import unittest
import hashlib
import json
from pathlib import Path
import tempfile
from uuid import UUID

from backend.app.agent_workspace import AgentWorkspaceAuditBuffer, AgentWorkspaceBroker, AuditCapacityError
from backend.app.agent_workspace.application.audit_worker import AgentWorkspaceAuditWorker
from scripts.execute_g10_agent_workspace_audit import (
    REQUIRED_INPUT_PATHS,
    SESSION_ID,
    WORKSPACE_ID,
    build_acceptance_buffer,
    canonical,
    current_commit,
    dry_run_report,
    validate_plan,
    validate_migration_statements,
)
from scripts.build_g10_agent_workspace_audit_successor_plan import build_plan


class _Connection:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True


class _Adapter:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.facts: list[object] = []

    async def append(self, _connection: object, fact: object) -> None:
        if self.fail:
            raise RuntimeError("bounded failure")
        self.facts.append(fact)


class AgentWorkspaceAuditRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def test_guest_workspace_never_enqueues_audit_facts(self) -> None:
        buffer = AgentWorkspaceAuditBuffer(enabled=True)
        broker = AgentWorkspaceBroker(audit_buffer=buffer, workspace_id_factory=lambda: WORKSPACE_ID)
        broker.create(session_id=SESSION_ID, user_id=9000001, mode="guest")
        self.assertEqual(0, buffer.pending_count)

    def test_demo_workspace_captures_public_events_and_directive_states(self) -> None:
        buffer = AgentWorkspaceAuditBuffer(enabled=True)
        broker = AgentWorkspaceBroker(audit_buffer=buffer, workspace_id_factory=lambda: WORKSPACE_ID)
        snapshot, _ = broker.create(session_id=SESSION_ID, user_id=1001, mode="demo")
        self.assertEqual(14, buffer.pending_count)
        directive = snapshot["directives"][0]
        broker.directive_action(
            WORKSPACE_ID, user_id=1001,
            directive_id=UUID(str(directive["directive_id"])), action="ACCEPT",
        )
        self.assertEqual(16, buffer.pending_count)
        serialised = str(buffer.snapshot()).lower()
        self.assertNotIn("prompt", serialised)
        self.assertNotIn("password", serialised)

    def test_fixed_replay_is_deterministic_and_exactly_bounded(self) -> None:
        first = build_acceptance_buffer().snapshot()
        second = build_acceptance_buffer().snapshot()
        self.assertEqual(first, second)
        report = dry_run_report()
        self.assertEqual(11, report["workspace_event_facts"])
        self.assertEqual(5, report["directive_state_facts"])
        self.assertEqual(17, report["maximum_rows"])
        self.assertEqual(0, report["database_connections"])
        self.assertEqual(0, report["deepseek_requests"])

    def test_capacity_rejects_before_overflow(self) -> None:
        buffer = AgentWorkspaceAuditBuffer(enabled=True, max_facts=1)
        facts = build_acceptance_buffer().snapshot()
        buffer._append(facts[0].event_uuid, facts[0])  # bounded queue unit seam
        with self.assertRaises(AuditCapacityError):
            buffer._append(facts[1].event_uuid, facts[1])
        self.assertEqual(1, buffer.pending_count)
        self.assertEqual(1, buffer.rejected_count)

    async def test_worker_acknowledges_only_committed_batch(self) -> None:
        buffer = build_acceptance_buffer()
        connection = _Connection()

        async def factory() -> _Connection:
            return connection

        worker = AgentWorkspaceAuditWorker(
            buffer=buffer, adapter=_Adapter(), connection_factory=factory, max_batch=16
        )
        report = await worker.drain_once()
        self.assertEqual(16, report.appended)
        self.assertEqual(0, report.remaining)
        self.assertEqual(1, connection.commits)
        self.assertEqual(0, connection.rollbacks)

    async def test_worker_failure_keeps_queue_and_reports_without_compensation(self) -> None:
        buffer = build_acceptance_buffer()
        connection = _Connection()

        async def factory() -> _Connection:
            return connection

        worker = AgentWorkspaceAuditWorker(
            buffer=buffer, adapter=_Adapter(fail=True), connection_factory=factory, max_batch=8
        )
        report = await worker.drain_once()
        self.assertEqual(0, report.appended)
        self.assertEqual(16, report.remaining)
        self.assertEqual(1, connection.rollbacks)
        self.assertEqual(0, connection.commits)

    def test_migration_validator_rejects_non_allowlisted_operations(self) -> None:
        with self.assertRaises(ValueError):
            validate_migration_statements(
                "CREATE TABLE IF NOT EXISTS agent_workspace_event (id INT);"
                "CREATE TABLE IF NOT EXISTS interaction_directive_fact (id INT);"
                "DELETE FROM recpro_schema_migration;"
            )

    def test_successor_plan_binds_all_runtime_inputs_and_validates(self) -> None:
        plan = build_plan(reviewed_commit=current_commit(), created_at="2026-08-21T05:00:00Z")
        self.assertEqual(set(plan["input_hashes"]), REQUIRED_INPUT_PATHS)
        self.assertEqual("APPLY", plan["mode"])
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "successor.json"
            path.write_text(json.dumps(plan), encoding="utf-8")
            validated = validate_plan(
                path, plan_id=str(plan["plan_id"]), approved_hash=str(plan["plan_hash"])
            )
        self.assertEqual(plan["plan_id"], validated["plan_id"])

    def test_successor_plan_rejects_any_changed_runtime_input_hash(self) -> None:
        plan = build_plan(reviewed_commit=current_commit(), created_at="2026-08-21T05:00:00Z")
        plan["input_hashes"]["scripts/reconcile_g10_agent_workspace_audit.py"] = "0" * 64
        unsigned = dict(plan)
        unsigned.pop("plan_hash")
        plan["plan_hash"] = hashlib.sha256(canonical(unsigned)).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "tampered.json"
            path.write_text(json.dumps(plan), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "input hash"):
                validate_plan(
                    path, plan_id=str(plan["plan_id"]), approved_hash=str(plan["plan_hash"])
                )


if __name__ == "__main__":
    unittest.main()
