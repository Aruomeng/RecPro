"""Platform adapters and explicit runtime composition helpers."""

from backend.app.platform.mysql import MySQLConnectionPool, PooledConnectionLease

__all__ = ["MySQLConnectionPool", "PooledConnectionLease"]
