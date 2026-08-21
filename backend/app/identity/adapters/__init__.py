"""Infrastructure adapters for the Identity bounded context."""

from backend.app.identity.adapters.mysql import MySQLIdentityRepository

__all__ = ["MySQLIdentityRepository"]
