from __future__ import annotations

import unittest
from pathlib import Path

from scripts.safety_scan import (
    _git_deletion_violations,
    find_git_history_violations,
    find_python_ast_violations,
    find_repository_interface_violations,
    find_text_violations,
    should_scan,
)


class SafetyScanTest(unittest.TestCase):
    def test_safe_append_only_statements_pass(self) -> None:
        source = """
INSERT INTO behavior_event(event_uuid) VALUES ('event-1');
UPDATE outbox SET status = 'DONE' WHERE id = 1;
docker compose stop
"""
        self.assertEqual([], find_text_violations("safe.sql", source))

    def test_destructive_sql_is_rejected(self) -> None:
        source = "DE" + "LETE FROM behavior_event WHERE id = 1"
        codes = {item.code for item in find_text_violations("bad.sql", source)}
        self.assertIn("SQL_DELETE", codes)

    def test_destructive_file_command_is_rejected(self) -> None:
        source = "r" + "m -rf ./data"
        codes = {item.code for item in find_text_violations("bad.sh", source)}
        self.assertIn("FILE_REMOVE", codes)

    def test_volume_removal_is_rejected(self) -> None:
        source = "docker volume " + "prune"
        codes = {item.code for item in find_text_violations("bad.sh", source)}
        self.assertIn("DOCKER_VOLUME_REMOVE", codes)

    def test_destructive_repository_method_is_rejected(self) -> None:
        source = (
            "class ResourceRepository:\n    def "
            + "de"
            + "lete(self, resource_id: int): ...\n"
        )
        violations = find_repository_interface_violations(
            "backend/app/catalog/ports/resource_repository.py", source
        )
        self.assertEqual("DESTRUCTIVE_REPOSITORY_METHOD", violations[0].code)

    def test_multiline_destructive_sql_is_rejected(self) -> None:
        source = "DE" + "LETE\nFROM behavior_event WHERE id = 1"
        codes = {item.code for item in find_text_violations("bad.sql", source)}
        self.assertIn("SQL_DELETE", codes)

    def test_file_directory_removal_is_rejected(self) -> None:
        source = "Path('data')." + "rm" + "dir()"
        codes = {item.code for item in find_text_violations("bad.py", source)}
        self.assertIn("FILE_RMDIR", codes)

    def test_chroma_reset_is_rejected(self) -> None:
        source = "chroma_client." + "reset()"
        codes = {item.code for item in find_text_violations("bad.py", source)}
        self.assertIn("CHROMA_RESET", codes)

    def test_git_worktree_discard_is_rejected(self) -> None:
        source = "git " + "restore README.md"
        codes = {item.code for item in find_text_violations("bad.sh", source)}
        self.assertIn("GIT_DISCARD_RESTORE", codes)

    def test_git_checkout_discard_is_rejected(self) -> None:
        source = "git " + "checkout -- README.md"
        codes = {item.code for item in find_text_violations("bad.sh", source)}
        self.assertIn("GIT_DISCARD_CHECKOUT", codes)

    def test_plain_file_remove_command_is_rejected(self) -> None:
        source = "r" + "m ./data.db"
        codes = {item.code for item in find_text_violations("bad.sh", source)}
        self.assertIn("FILE_REMOVE", codes)

    def test_subprocess_file_remove_is_rejected(self) -> None:
        source = 'import subprocess\nsubprocess.run(["r' + 'm", "data.db"])\n'
        violations = find_python_ast_violations("bad.py", source)
        self.assertEqual("DESTRUCTIVE_SUBPROCESS_COMMAND", violations[0].code)

    def test_database_principal_drop_is_rejected(self) -> None:
        source = "DR" + "OP USER app_user"
        codes = {item.code for item in find_text_violations("bad.sql", source)}
        self.assertIn("SQL_DROP", codes)

    def test_path_replace_overwrite_risk_is_rejected(self) -> None:
        source = 'from pathlib import Path\nPath("x").replace("y")\n'
        violations = find_python_ast_violations("bad.py", source)
        self.assertEqual("FILE_REPLACE_OVERWRITE_RISK", violations[0].code)

    def test_path_variable_replace_overwrite_risk_is_rejected(self) -> None:
        source = 'from pathlib import Path\ntarget = Path("x")\ntarget.replace("y")\n'
        violations = find_python_ast_violations("bad.py", source)
        self.assertEqual("FILE_REPLACE_OVERWRITE_RISK", violations[0].code)

    def test_string_replace_is_not_treated_as_file_overwrite(self) -> None:
        source = 'path = "a/b"\nnormalized = path.replace("/", ".")\n'
        self.assertEqual([], find_python_ast_violations("safe.py", source))

    def test_repository_purge_method_is_rejected(self) -> None:
        source = "class Repository:\n    def " + "purge" + "_all(self): ...\n"
        violations = find_repository_interface_violations(
            "backend/app/catalog/ports/resource_repository.py",
            source,
        )
        self.assertEqual("DESTRUCTIVE_REPOSITORY_METHOD", violations[0].code)

    def test_frontend_and_package_scripts_are_scanned(self) -> None:
        self.assertTrue(should_scan(Path("frontend/src/app.ts")))
        self.assertTrue(should_scan(Path("frontend/src/App.vue")))
        self.assertTrue(should_scan(Path("package.json")))

    def test_executable_files_cannot_escape_under_docs_or_safety_tests(self) -> None:
        self.assertTrue(should_scan(Path("docs/cleanup.sh")))
        self.assertTrue(should_scan(Path("tests/safety/test_safety_scan.py")))

    def test_unrelated_cache_delete_call_does_not_claim_chroma(self) -> None:
        source = "cache." + "de" + "lete(key)"
        codes = {item.code for item in find_text_violations("cache.ts", source)}
        self.assertNotIn("CHROMA_DELETE", codes)
        self.assertIn("GENERIC_DESTRUCTIVE_CALL", codes)

    def test_os_replace_and_shutil_move_are_rejected(self) -> None:
        for source in ('os.replace("a", "b")', 'shutil.move("a", "b")'):
            with self.subTest(source=source):
                violations = find_python_ast_violations("bad.py", source)
                self.assertEqual("FILE_MOVE_OR_OVERWRITE_RISK", violations[0].code)

    def test_non_sensitive_clear_method_name_is_allowed(self) -> None:
        source = "def clear():\n    return None\n"
        self.assertEqual(
            [],
            find_repository_interface_violations(
                "backend/app/profile/domain/selection.py",
                source,
            ),
        )

    def test_sensitive_database_delete_calls_are_rejected(self) -> None:
        sources = (
            "session." + "de" + "lete(row)",
            "query." + "de" + "lete()",
            "delete" + "(Resource)",
            "table." + "de" + "lete()",
        )
        for source in sources:
            with self.subTest(source=source):
                violations = find_python_ast_violations(
                    "backend/app/catalog/adapters/mysql/resource_repository.py",
                    source,
                )
                self.assertIn(
                    "SENSITIVE_DESTRUCTIVE_CALL",
                    {item.code for item in violations},
                )

    def test_database_delete_call_is_rejected_outside_adapter_path(self) -> None:
        source = "session." + "de" + "lete(row)\n"
        violations = find_python_ast_violations(
            "backend/app/catalog/application/service.py",
            source,
        )
        self.assertIn(
            "SENSITIVE_DESTRUCTIVE_CALL",
            {item.code for item in violations},
        )

    def test_prefixed_drop_calls_and_alembic_alias_are_rejected(self) -> None:
        sources = (
            "Base.metadata." + "dr" + "op_all(bind=engine)\n",
            "from alembic import op as operations\noperations."
            + "dr"
            + "op_table('resource')\n",
        )
        for source in sources:
            with self.subTest(source=source):
                violations = find_python_ast_violations(
                    "backend/app/catalog/migrations/revision.py",
                    source,
                )
                self.assertIn(
                    "SENSITIVE_DESTRUCTIVE_CALL",
                    {item.code for item in violations},
                )

    def test_non_sensitive_collection_clear_call_is_allowed(self) -> None:
        self.assertEqual(
            [],
            find_python_ast_violations(
                "backend/app/catalog/domain/selection.py",
                "selected.clear()\n",
            ),
        )

    def test_committed_delete_and_rename_records_are_rejected(self) -> None:
        output = "D\tdocs/old.md\nR100\told.py\tnew.py\nM\tkept.py\n"
        violations = find_git_history_violations(output)
        self.assertEqual(2, len(violations))
        self.assertTrue(
            all(item.code == "GIT_HISTORY_DELETE_OR_RENAME" for item in violations)
        )

    def test_history_scan_uses_per_commit_log_so_restoration_cannot_hide_event(self) -> None:
        from subprocess import CompletedProcess
        from unittest.mock import patch

        status = CompletedProcess(
            args=["git", "status"],
            returncode=0,
            stdout="",
            stderr="",
        )
        history = CompletedProcess(
            args=["git", "log"],
            returncode=0,
            stdout="D\tprotected.md\nA\tprotected.md\n",
            stderr="",
        )
        with patch(
            "scripts.safety_scan.subprocess.run",
            side_effect=(status, history),
        ) as mocked_run:
            violations = _git_deletion_violations(Path("."), base_ref="base123")

        self.assertEqual("GIT_HISTORY_DELETE_OR_RENAME", violations[0].code)
        history_command = mocked_run.call_args_list[1].args[0]
        self.assertEqual("log", history_command[1])
        self.assertIn("base123..HEAD", history_command)

    def test_aliased_database_delete_call_is_rejected(self) -> None:
        source = (
            "from sqlalchemy import "
            + "de"
            + "lete as build_statement\n"
            + "build_statement(Resource)\n"
        )
        violations = find_python_ast_violations(
            "backend/app/catalog/adapters/mysql/resource_repository.py",
            source,
        )
        self.assertIn(
            "SENSITIVE_DESTRUCTIVE_CALL",
            {item.code for item in violations},
        )

    def test_literal_getattr_database_delete_call_is_rejected(self) -> None:
        source = 'getattr(session, "' + 'delete")(row)\n'
        violations = find_python_ast_violations(
            "backend/app/catalog/adapters/mysql/resource_repository.py",
            source,
        )
        self.assertIn(
            "SENSITIVE_DESTRUCTIVE_CALL",
            {item.code for item in violations},
        )

    def test_aliased_file_delete_call_is_rejected(self) -> None:
        sources = (
            "import os as operating\noperating." + "remove(path)\n",
            "from shutil import " + "rmtree as cleanup\ncleanup(path)\n",
        )
        for source in sources:
            with self.subTest(source=source):
                violations = find_python_ast_violations("tools/cleanup.py", source)
                self.assertIn("FILE_DELETE_CALL", {item.code for item in violations})

    def test_frontend_orm_destructive_call_is_rejected(self) -> None:
        source = "client.book." + "de" + "leteMany({})"
        codes = {item.code for item in find_text_violations("worker.ts", source)}
        self.assertIn("GENERIC_DESTRUCTIVE_CALL", codes)

    def test_aliased_subprocess_destructive_command_is_rejected(self) -> None:
        source = (
            "import subprocess as sp\n"
            + 'sp.run(["r'
            + 'm", "data.db"])\n'
        )
        violations = find_python_ast_violations("tools/runner.py", source)
        self.assertIn(
            "DESTRUCTIVE_SUBPROCESS_COMMAND",
            {item.code for item in violations},
        )

    def test_assigned_database_delete_callable_is_rejected(self) -> None:
        source = "operation = session." + "delete\noperation(row)\n"
        violations = find_python_ast_violations(
            "backend/app/catalog/adapters/mysql/resource_repository.py",
            source,
        )
        self.assertIn(
            "SENSITIVE_DESTRUCTIVE_CALL",
            {item.code for item in violations},
        )


if __name__ == "__main__":
    unittest.main()
