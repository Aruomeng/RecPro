"""Platform adapters and explicit runtime composition helpers."""

from backend.app.platform.mysql import (
    MySQLConnectionPool,
    MySQLPoolSnapshot,
    PooledConnectionLease,
)
from backend.app.platform.lifecycle import RuntimeResourceCloseError, RuntimeResourceRegistry

__all__ = [
    "MySQLConnectionPool",
    "MySQLPoolSnapshot",
    "PooledConnectionLease",
    "RuntimeResourceCloseError",
    "RuntimeResourceRegistry",
]
