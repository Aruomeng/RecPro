"""Read-only MySQL connectivity and least-privilege readiness probe."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterable, Mapping

import asyncmy
from pydantic import SecretStr

from backend.app.observability.domain import ComponentReadiness, ComponentStatus
from backend.app.shared_kernel.contracts.errors import ErrorCode


_GRANT_PATTERN = re.compile(
    r"^GRANT\s+(?P<privileges>.+?)\s+ON\s+(?P<scope>.+?)\s+TO\s+",
    flags=re.IGNORECASE,
)
_IDENTIFIER_TOKEN_PATTERN = re.compile(
    r"^(?:`(?P<quoted>[A-Za-z][A-Za-z0-9_]*)`|(?P<plain>[A-Za-z][A-Za-z0-9_]*))$"
)
_SCOPE_PATTERN = re.compile(
    r"^\s*(?P<database>\*|`[a-z][a-z0-9_]*`|[a-z][a-z0-9_]*)"
    r"\s*\.\s*"
    r"(?P<object>\*|`[a-z][a-z0-9_]*`|[a-z][a-z0-9_]*)\s*$"
)
_ALLOWED_PRIVILEGES = frozenset({"USAGE", "SELECT", "INSERT", "UPDATE"})
_FORBIDDEN_PRIVILEGES = frozenset(
    {
        "ALL",
        "ALTER",
        "CREATE",
        "DELETE",
        "DROP",
        "EVENT",
        "EXECUTE",
        "FILE",
        "GRANT OPTION",
        "INDEX",
        "PROCESS",
        "REFERENCES",
        "RELOAD",
        "REPLICATION CLIENT",
        "REPLICATION SLAVE",
        "SHOW DATABASES",
        "SHUTDOWN",
        "SUPER",
        "TRIGGER",
    }
)


def _split_privileges(value: str) -> tuple[str, ...]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for character in value:
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        if character == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(character)
    if current:
        parts.append("".join(current).strip())
    return tuple(parts)


def _privilege_name(value: str) -> str:
    return value.split("(", maxsplit=1)[0].strip().upper()


def _privilege_columns(value: str) -> frozenset[str] | None:
    match = re.fullmatch(r"\s*[A-Za-z ]+\s*\((?P<columns>[^)]+)\)\s*", value)
    if match is None:
        return None
    columns: set[str] = set()
    for raw_item in match.group("columns").split(","):
        identifier = _IDENTIFIER_TOKEN_PATTERN.fullmatch(raw_item.strip())
        if identifier is None:
            return None
        columns.add((identifier.group("quoted") or identifier.group("plain")).lower())
    return frozenset(columns) if columns else None


def _normalized_scope(value: str) -> str | None:
    match = _SCOPE_PATTERN.fullmatch(value)
    if match is None:
        return None
    database = match.group("database").replace("`", "")
    object_name = match.group("object").replace("`", "")
    return f"{database}.{object_name}"


@dataclass(frozen=True, slots=True)
class GrantSafetyEvaluator:
    """Conservatively accept only the runtime role's documented permissions."""

    database: str
    update_column_allowlist: Mapping[str, frozenset[str]] | None = None

    def __post_init__(self) -> None:
        if self.update_column_allowlist is None:
            object.__setattr__(
                self,
                "update_column_allowlist",
                MappingProxyType(
                    {
                        "outbox_event": frozenset(
                            {
                                "attempt_count",
                                "available_at",
                                "last_error",
                                "locked_at",
                                "locked_by",
                                "status",
                            }
                        ),
                        "recommendation_task": frozenset({"status", "updated_at"}),
                        "worker_heartbeat": frozenset({"heartbeat_at", "status"}),
                        "user_resource_state": frozenset(
                            {
                                "suppress_until",
                                "source_event_id",
                                "last_feedback_at",
                                "state_version",
                            }
                        ),
                    }
                ),
            )
        else:
            object.__setattr__(
                self,
                "update_column_allowlist",
                MappingProxyType(dict(self.update_column_allowlist)),
            )

    def grants_are_safe(self, grants: Iterable[str]) -> bool:
        seen = False
        schema_privileges: set[str] = set()
        database_scope = f"{self.database.lower()}.*"
        for statement in grants:
            seen = True
            if not self._grant_is_safe(statement):
                return False
            match = _GRANT_PATTERN.match(statement.strip())
            if match is not None and _normalized_scope(match.group("scope")) == database_scope:
                schema_privileges.update(
                    _privilege_name(item)
                    for item in _split_privileges(match.group("privileges"))
                )
        return seen and {"SELECT", "INSERT"}.issubset(schema_privileges)

    def _grant_is_safe(self, statement: str) -> bool:
        normalized_statement = " ".join(statement.upper().split())
        if " WITH GRANT OPTION" in normalized_statement or "``" in statement:
            return False
        match = _GRANT_PATTERN.match(statement.strip())
        if match is None:
            return False

        raw_privileges = _split_privileges(match.group("privileges"))
        privileges = tuple(_privilege_name(item) for item in raw_privileges)
        if not privileges or any(item in _FORBIDDEN_PRIVILEGES for item in privileges):
            return False
        if any(item not in _ALLOWED_PRIVILEGES for item in privileges):
            return False

        scope = _normalized_scope(match.group("scope"))
        if scope is None:
            return False
        if privileges == ("USAGE",):
            return scope == "*.*"
        database_scope = f"{self.database.lower()}.*"
        if scope == "*.*" or not scope.startswith(f"{self.database.lower()}."):
            return False
        if "UPDATE" not in privileges:
            return scope == database_scope or scope.count(".") == 1
        if scope == database_scope:
            return False
        table = scope.split(".", maxsplit=1)[1]
        allowed_columns = (self.update_column_allowlist or {}).get(table)
        if not allowed_columns:
            return False
        update_columns = tuple(
            _privilege_columns(raw)
            for raw, name in zip(raw_privileges, privileges, strict=True)
            if name == "UPDATE"
        )
        return bool(update_columns) and all(
            columns is not None
            and bool(columns)
            and columns.issubset(allowed_columns)
            for columns in update_columns
        )


@dataclass(frozen=True, slots=True)
class AsyncMySQLReadinessProbe:
    host: str
    port: int
    database: str
    user: str
    password: SecretStr
    connect_timeout_seconds: float
    persistence_probe_id: str

    async def check(self) -> ComponentReadiness:
        connection = None
        try:
            async with asyncio.timeout(self.connect_timeout_seconds):
                connection = await asyncmy.connect(
                    host=self.host,
                    port=self.port,
                    user=self.user,
                    password=self.password.get_secret_value(),
                    db=self.database,
                    connect_timeout=self.connect_timeout_seconds,
                    read_timeout=self.connect_timeout_seconds,
                    charset="utf8mb4",
                    autocommit=True,
                )
                async with connection.cursor() as cursor:
                    await cursor.execute(
                        "SELECT probe_id, DATABASE(), CURRENT_USER(), "
                        "@@character_set_database, @@character_set_connection "
                        "FROM recpro_runtime_probe "
                        "WHERE probe_id = %s",
                        (self.persistence_probe_id,),
                    )
                    row = await cursor.fetchone()
                    if (
                        row is None
                        or len(row) != 5
                        or row[0] != self.persistence_probe_id
                        or row[1] != self.database
                        or str(row[2]).split("@", maxsplit=1)[0] != self.user
                        or row[3] != "utf8mb4"
                        or row[4] != "utf8mb4"
                    ):
                        raise RuntimeError(
                            "database identity, charset, or persistence probe is unavailable"
                        )
                    await cursor.execute("SHOW GRANTS")
                    rows = await cursor.fetchall()
            grants = tuple(str(row[0]) for row in rows if row)
            if not GrantSafetyEvaluator(self.database).grants_are_safe(grants):
                return ComponentReadiness(
                    status=ComponentStatus.DOWN,
                    required=True,
                    error_code=ErrorCode.UNSAFE_DATABASE_PRIVILEGES.value,
                )
            return ComponentReadiness(
                status=ComponentStatus.UP,
                required=True,
                active_version=self.persistence_probe_id,
            )
        except Exception:
            return ComponentReadiness(
                status=ComponentStatus.DOWN,
                required=True,
                error_code=ErrorCode.CORE_STORAGE_UNAVAILABLE.value,
            )
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass
