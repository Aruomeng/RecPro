from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

from pydantic import SecretStr

from backend.app.observability.adapters.mysql_readiness import (
    AsyncMySQLReadinessProbe,
    GrantSafetyEvaluator,
)
from backend.app.observability.domain import ComponentStatus
from backend.app.shared_kernel.contracts.errors import ErrorCode


class GrantSafetyEvaluatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.evaluator = GrantSafetyEvaluator("recpro")

    def test_documented_read_and_append_privileges_are_safe(self) -> None:
        grants = (
            "GRANT USAGE ON *.* TO `runtime`@`%`",
            "GRANT SELECT, INSERT ON `recpro`.* TO `runtime`@`%`",
            "GRANT UPDATE (`status`) ON `recpro`.`outbox_event` TO `runtime`@`%`",
        )
        self.assertTrue(self.evaluator.grants_are_safe(grants))

    def test_empty_or_unparseable_grants_fail_closed(self) -> None:
        self.assertFalse(self.evaluator.grants_are_safe(()))
        self.assertFalse(self.evaluator.grants_are_safe(("unparseable",)))

    def test_privilege_expansion_is_rejected(self) -> None:
        unsafe_grants = (
            "GRANT ALL PRIVILEGES ON `recpro`.* TO `runtime`@`%`",
            "GRANT DE" + "LETE ON `recpro`.* TO `runtime`@`%`",
            "GRANT CREATE ON `recpro`.* TO `runtime`@`%`",
            "GRANT SELECT ON *.* TO `runtime`@`%`",
            "GRANT SELECT ON `other`.* TO `runtime`@`%`",
            "GRANT UPDATE ON `recpro`.* TO `runtime`@`%`",
            "GRANT UPDATE ON `recpro`.`outbox_event` TO `runtime`@`%`",
            (
                "GRANT UPDATE (`status`, `unrestricted_column`) "
                "ON `recpro`.`outbox_event` TO `runtime`@`%`"
            ),
            "GRANT SELECT ON `recpro`.* TO `runtime`@`%` WITH GRANT OPTION",
        )
        for statement in unsafe_grants:
            with self.subTest(statement=statement):
                self.assertFalse(self.evaluator.grants_are_safe((statement,)))

    def test_required_select_and_insert_must_both_be_present(self) -> None:
        usage = "GRANT USAGE ON *.* TO `runtime`@`%`"
        select = "GRANT SELECT ON `recpro`.* TO `runtime`@`%`"
        insert = "GRANT INSERT ON `recpro`.* TO `runtime`@`%`"

        self.assertFalse(self.evaluator.grants_are_safe((usage,)))
        self.assertFalse(self.evaluator.grants_are_safe((usage, select)))
        self.assertFalse(self.evaluator.grants_are_safe((usage, insert)))
        self.assertTrue(self.evaluator.grants_are_safe((usage, select, insert)))

    def test_escaped_identifier_cannot_alias_an_allowed_name(self) -> None:
        invalid_alias_grants = (
            (
                "GRANT SELECT, INSERT ON `recpro`.* TO `runtime`@`%`",
                "GRANT UPDATE (`s``tatus`) ON `recpro`.`outbox``_event` TO `runtime`@`%`",
            ),
            (
                "GRANT SELECT, INSERT ON `recpro`.* TO `runtime`@`%`",
                "GRANT UPDATE (`status`) ON `rec pro`.`outbox_event` TO `runtime`@`%`",
            ),
            (
                "GRANT SELECT, INSERT ON `recpro`.* TO `runtime`@`%`",
                "GRANT UPDATE (`s tatus`) ON `recpro`.`outbox_event` TO `runtime`@`%`",
            ),
            (
                "GRANT SELECT, INSERT ON `recpro`.* TO `runtime`@`%`",
                "GRANT UPDATE (`status`) ON `recpro`.`OUTBOX_EVENT` TO `runtime`@`%`",
            ),
        )
        for grants in invalid_alias_grants:
            with self.subTest(grants=grants):
                self.assertFalse(self.evaluator.grants_are_safe(grants))


class FakeCursor:
    def __init__(
        self,
        grants: tuple[str, ...],
        probe_id: str,
        identity: tuple[str, str, str, str] = (
            "recpro",
            "runtime@%",
            "utf8mb4",
            "utf8mb4",
        ),
    ) -> None:
        self.grants = grants
        self.probe_id = probe_id
        self.identity = identity
        self.statements: list[tuple[str, tuple[str, ...] | None]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def execute(
        self, statement: str, parameters: tuple[str, ...] | None = None
    ) -> None:
        self.statements.append((statement, parameters))

    async def fetchone(self):
        return (self.probe_id, *self.identity)

    async def fetchall(self):
        return tuple((grant,) for grant in self.grants)


class FakeConnection:
    def __init__(
        self,
        grants: tuple[str, ...],
        probe_id: str,
        identity: tuple[str, str, str, str] = (
            "recpro",
            "runtime@%",
            "utf8mb4",
            "utf8mb4",
        ),
    ) -> None:
        self.fake_cursor = FakeCursor(grants, probe_id, identity)
        self.closed = False

    def cursor(self) -> FakeCursor:
        return self.fake_cursor

    def close(self) -> None:
        self.closed = True


class MySQLReadinessProbeTest(unittest.IsolatedAsyncioTestCase):
    probe_id = "libramas-g1-researcher42-instance07"

    def probe(self, *, timeout: float = 1.0) -> AsyncMySQLReadinessProbe:
        return AsyncMySQLReadinessProbe(
            host="isolated.invalid",
            port=3306,
            database="recpro",
            user="runtime",
            password=SecretStr("test-password"),
            connect_timeout_seconds=timeout,
            persistence_probe_id=self.probe_id,
        )

    async def test_probe_executes_only_persistent_marker_and_grant_reads(self) -> None:
        connection = FakeConnection(
            (
                "GRANT USAGE ON *.* TO `runtime`@`%`",
                "GRANT SELECT, INSERT ON `recpro`.* TO `runtime`@`%`",
            ),
            self.probe_id,
        )
        with patch(
            "backend.app.observability.adapters.mysql_readiness.asyncmy.connect",
            AsyncMock(return_value=connection),
        ):
            result = await self.probe().check()

        self.assertEqual(ComponentStatus.UP, result.status)
        self.assertEqual(
            [
                (
                    "SELECT probe_id, DATABASE(), CURRENT_USER(), "
                    "@@character_set_database, @@character_set_connection "
                    "FROM recpro_runtime_probe "
                    "WHERE probe_id = %s",
                    (self.probe_id,),
                ),
                ("SHOW GRANTS", None),
            ],
            connection.fake_cursor.statements,
        )
        self.assertEqual(self.probe_id, result.active_version)
        self.assertTrue(connection.closed)

    async def test_wrong_database_identity_or_charset_fails_closed(self) -> None:
        unsafe_identities = (
            ("other", "runtime@%", "utf8mb4", "utf8mb4"),
            ("recpro", "another@%", "utf8mb4", "utf8mb4"),
            ("recpro", "runtime@%", "latin1", "utf8mb4"),
            ("recpro", "runtime@%", "utf8mb4", "latin1"),
        )
        for identity in unsafe_identities:
            with self.subTest(identity=identity):
                connection = FakeConnection(
                    ("GRANT SELECT, INSERT ON `recpro`.* TO `runtime`@`%`",),
                    self.probe_id,
                    identity,
                )
                with patch(
                    "backend.app.observability.adapters.mysql_readiness.asyncmy.connect",
                    AsyncMock(return_value=connection),
                ):
                    result = await self.probe().check()

                self.assertEqual(ComponentStatus.DOWN, result.status)
                self.assertEqual(
                    ErrorCode.CORE_STORAGE_UNAVAILABLE.value,
                    result.error_code,
                )

    async def test_unsafe_grant_has_specific_error_code(self) -> None:
        connection = FakeConnection(
            ("GRANT ALL PRIVILEGES ON `recpro`.* TO `runtime`@`%`",),
            self.probe_id,
        )
        with patch(
            "backend.app.observability.adapters.mysql_readiness.asyncmy.connect",
            AsyncMock(return_value=connection),
        ):
            result = await self.probe().check()

        self.assertEqual(ComponentStatus.DOWN, result.status)
        self.assertEqual(ErrorCode.UNSAFE_DATABASE_PRIVILEGES.value, result.error_code)
        self.assertTrue(connection.closed)

    async def test_connection_failure_is_sanitized(self) -> None:
        with patch(
            "backend.app.observability.adapters.mysql_readiness.asyncmy.connect",
            AsyncMock(side_effect=OSError("host detail must stay private")),
        ):
            result = await self.probe().check()

        self.assertEqual(ComponentStatus.DOWN, result.status)
        self.assertEqual(ErrorCode.CORE_STORAGE_UNAVAILABLE.value, result.error_code)

    async def test_total_probe_timeout_closes_a_half_open_connection(self) -> None:
        connection = FakeConnection(
            ("GRANT SELECT, INSERT ON `recpro`.* TO `runtime`@`%`",),
            self.probe_id,
        )

        async def block_forever(
            statement: str, parameters: tuple[str, ...] | None = None
        ) -> None:
            await asyncio.Event().wait()

        connection.fake_cursor.execute = block_forever  # type: ignore[method-assign]
        with patch(
            "backend.app.observability.adapters.mysql_readiness.asyncmy.connect",
            AsyncMock(return_value=connection),
        ):
            result = await self.probe(timeout=0.01).check()

        self.assertEqual(ComponentStatus.DOWN, result.status)
        self.assertEqual(ErrorCode.CORE_STORAGE_UNAVAILABLE.value, result.error_code)
        self.assertTrue(connection.closed)

    async def test_connection_close_failure_cannot_escape_the_probe_boundary(self) -> None:
        connection = FakeConnection(
            (
                "GRANT USAGE ON *.* TO `runtime`@`%`",
                "GRANT SELECT, INSERT ON `recpro`.* TO `runtime`@`%`",
            ),
            self.probe_id,
        )
        close = Mock(side_effect=OSError("private close failure"))
        connection.close = close  # type: ignore[method-assign]
        with patch(
            "backend.app.observability.adapters.mysql_readiness.asyncmy.connect",
            AsyncMock(return_value=connection),
        ):
            result = await self.probe().check()

        self.assertEqual(ComponentStatus.UP, result.status)
        self.assertEqual(self.probe_id, result.active_version)
        close.assert_called_once_with()
