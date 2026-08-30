"""Platform adapters and explicit runtime composition helpers."""

from backend.app.platform.mysql import (
    MySQLConnectionPool,
    MySQLPoolSnapshot,
    PooledConnectionLease,
)
from backend.app.platform.lifecycle import RuntimeResourceCloseError, RuntimeResourceRegistry
from backend.app.platform.oidc import (
    JWKSCache,
    OIDCBearerTokenResolver,
    OIDCIdentityBinding,
    OIDCIdentityMapper,
)

__all__ = [
    "MySQLConnectionPool",
    "MySQLPoolSnapshot",
    "PooledConnectionLease",
    "RuntimeResourceCloseError",
    "RuntimeResourceRegistry",
    "JWKSCache",
    "OIDCBearerTokenResolver",
    "OIDCIdentityBinding",
    "OIDCIdentityMapper",
]
