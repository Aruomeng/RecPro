"""Apply the narrow G5 runtime projection grant after its table exists."""

from __future__ import annotations

import asyncmy

from scripts.validate_runtime_env import DATABASE_IDENTIFIER_PATTERN, MYSQL_USER_PATTERN


G5_RUNTIME_UPDATE_COLUMNS = (
    "suppress_until",
    "source_event_id",
    "last_feedback_at",
    "state_version",
)


async def grant_g5_runtime_projection(
    *,
    host_port: int,
    database: str,
    root_password: str,
    runtime_user: str,
) -> None:
    """Grant only the four current-projection columns needed by feedback writes.

    The grant is deliberately separate from the MySQL init hook: the table is
    created by the forward migration, so applying it after that migration keeps
    fresh volumes bootable without broadening the runtime schema grant.
    """

    if DATABASE_IDENTIFIER_PATTERN.fullmatch(database) is None:
        raise ValueError("database identifier is unsafe")
    if MYSQL_USER_PATTERN.fullmatch(runtime_user) is None:
        raise ValueError("runtime user identifier is unsafe")
    if not root_password:
        raise ValueError("root password is required to apply the projection grant")
    columns = ", ".join(f"`{column}`" for column in G5_RUNTIME_UPDATE_COLUMNS)
    connection = await asyncmy.connect(
        host="127.0.0.1",
        port=host_port,
        user="root",
        password=root_password,
        db=database,
        connect_timeout=10,
        read_timeout=30,
        charset="utf8mb4",
        autocommit=True,
    )
    try:
        async with connection.cursor() as cursor:
            await cursor.execute(
                f"GRANT UPDATE ({columns}) ON `{database}`.`user_resource_state` "
                f"TO '{runtime_user}'@'%';"
            )
    finally:
        connection.close()


__all__ = ["G5_RUNTIME_UPDATE_COLUMNS", "grant_g5_runtime_projection"]
