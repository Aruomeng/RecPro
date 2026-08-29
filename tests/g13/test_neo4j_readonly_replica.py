from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
import unittest

from scripts.build_neo4j_readonly_replica_plan import build_plan
from scripts.execute_neo4j_readonly_replica_plan import apply_plan, dry_run_report
from scripts.build_neo4j_readonly_replica_successor_plan import build_plan as build_successor_plan
from scripts.execute_neo4j_readonly_replica_successor import (
    _tar_config,
    dry_run_report as successor_dry_run_report,
)
from scripts.build_neo4j_readonly_final_plan import build_plan as build_final_plan
from scripts.execute_neo4j_readonly_final_plan import dry_run_report as final_dry_run_report
from scripts.import_book_graph import canonical_json


class Neo4jReadOnlyReplicaPlanTests(unittest.TestCase):
    def test_dry_run_has_exact_graph_and_zero_connection_budget(self) -> None:
        report = dry_run_report()

        self.assertEqual(63388, report["v1"]["nodes"])
        self.assertEqual(191865, report["v1"]["relationships"])
        self.assertEqual(78129, report["v2"]["nodes"])
        self.assertEqual(206848, report["v2"]["relationships"])
        self.assertEqual(0, report["docker_connections"])
        self.assertEqual(0, report["database_connections"])
        self.assertEqual(0, report["database_deletions"])
        self.assertEqual(0, report["container_deletions"])
        self.assertEqual(0, report["volume_deletions"])

    def test_plan_is_deterministic_additive_and_binds_all_inputs(self) -> None:
        reviewed_commit = "a" * 40
        created_at = datetime(2026, 8, 29, 4, 10, tzinfo=UTC).isoformat()
        first = build_plan(reviewed_commit=reviewed_commit, created_at=created_at)
        second = build_plan(reviewed_commit=reviewed_commit, created_at=created_at)

        self.assertEqual(first, second)
        self.assertEqual("S2_INFRA_APPEND", first["classification"])
        self.assertEqual(141517, first["graph_append"]["total_nodes"])
        self.assertEqual(398713, first["graph_append"]["total_relationships"])
        self.assertEqual(1, first["maximum_changes"]["new_containers"])
        self.assertEqual(1, first["maximum_changes"]["new_volumes"])
        self.assertTrue(first["source_guard"]["must_remain_unchanged"])
        self.assertTrue(all(value == 0 for value in first["safety"].values()))
        self.assertIn("compose.neo4j-readonly.yaml", first["input_hashes"])
        self.assertIn(
            "scripts/execute_neo4j_readonly_replica_plan.py",
            first["input_hashes"],
        )
        without_hash = dict(first)
        without_hash.pop("plan_hash")
        self.assertEqual(
            first["plan_hash"],
            sha256(canonical_json(without_hash).encode()).hexdigest(),
        )

    def test_compose_is_local_additive_and_read_only_by_default(self) -> None:
        source = Path("compose.neo4j-readonly.yaml").read_text(encoding="utf-8")

        self.assertIn(
            'NEO4J_server_databases_default__to__read__only: "true"', source
        )
        self.assertIn("127.0.0.1:${RECPRO_READONLY_NEO4J_HTTP_HOST_PORT", source)
        self.assertIn("127.0.0.1:${RECPRO_READONLY_NEO4J_BOLT_HOST_PORT", source)
        self.assertIn("readonly_neo4j_data:/data", source)
        self.assertNotIn("external: true", source)

    def test_unsafe_run_id_fails_before_docker_or_database_access(self) -> None:
        with self.assertRaisesRegex(ValueError, "run id"):
            apply_plan(
                plan={}, source_env_file=Path(".env.user-secrets"),
                run_id="../../outside",
            )

    def test_successor_dry_run_is_zero_connection_and_zero_deletion(self) -> None:
        report = successor_dry_run_report()

        self.assertEqual(141517, report["replica_nodes_max"])
        self.assertEqual(398713, report["replica_relationships_max"])
        self.assertEqual(2, report["container_config_replacements_max"])
        self.assertEqual(0, report["new_containers"])
        self.assertEqual(0, report["new_volumes"])
        self.assertEqual(0, report["docker_connections"])
        self.assertEqual(0, report["database_connections"])
        self.assertEqual(0, report["container_deletions"])
        self.assertEqual(0, report["volume_deletions"])

    def test_successor_plan_binds_partial_state_and_is_deterministic(self) -> None:
        kwargs = {
            "reviewed_commit": "b" * 40,
            "created_at": "2026-08-29T09:00:00Z",
            "container_id": "c" * 64,
            "config_sha256": "d" * 64,
            "log_volume_name": "e" * 64,
        }
        first = build_successor_plan(**kwargs)
        second = build_successor_plan(**kwargs)

        self.assertEqual(first, second)
        self.assertEqual("S2_INFRA_APPEND_FAIL_FORWARD", first["classification"])
        self.assertEqual("c" * 64, first["partial_state"]["container_id"])
        self.assertEqual("d" * 64, first["partial_state"]["config_sha256"])
        self.assertEqual("e" * 64, first["partial_state"]["log_volume_name"])
        self.assertEqual(0, first["maximum_changes"]["new_containers"])
        self.assertEqual(0, first["maximum_changes"]["new_volumes"])
        self.assertTrue(all(value == 0 for value in first["safety"].values()))

    def test_successor_config_tar_contains_only_bounded_config_member(self) -> None:
        import io
        import tarfile

        payload = _tar_config(b"server.databases.default_to_read_only=true\n")
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r") as archive:
            members = archive.getmembers()
            self.assertEqual(["neo4j.conf"], [member.name for member in members])
            self.assertEqual(0o600, members[0].mode)

    def test_final_dry_run_has_explicit_additive_budget(self) -> None:
        report = final_dry_run_report()

        self.assertEqual(1, report["new_containers"])
        self.assertEqual(2, report["new_volumes"])
        self.assertEqual(600, report["graceful_stop_timeout_seconds"])
        self.assertEqual(141517, report["replica_nodes_max"])
        self.assertEqual(0, report["container_deletions"])
        self.assertEqual(0, report["volume_deletions"])
        self.assertEqual(0, report["docker_connections"])
        self.assertEqual(0, report["database_connections"])

    def test_final_plan_is_deterministic_and_retains_failed_replica(self) -> None:
        first = build_final_plan(
            reviewed_commit="f" * 40,
            created_at="2026-08-29T10:00:00Z",
        )
        second = build_final_plan(
            reviewed_commit="f" * 40,
            created_at="2026-08-29T10:00:00Z",
        )

        self.assertEqual(first, second)
        self.assertEqual(0, first["retained_failed_replica"]["allowed_changes"])
        self.assertEqual(2, first["maximum_changes"]["new_volumes"])
        self.assertEqual(600, first["dry_run"]["graceful_stop_timeout_seconds"])
        self.assertTrue(all(value == 0 for value in first["safety"].values()))

    def test_final_compose_names_both_data_and_log_volumes(self) -> None:
        source = Path("compose.neo4j-readonly-final.yaml").read_text(encoding="utf-8")

        self.assertIn("final_neo4j_data:/data", source)
        self.assertIn("final_neo4j_logs:/logs", source)
        self.assertIn('NEO4J_server_databases_default__to__read__only: "true"', source)


if __name__ == "__main__":
    unittest.main()
