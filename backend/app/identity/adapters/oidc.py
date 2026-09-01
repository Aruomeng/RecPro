"""Read-only OIDC subject mapper for the local IAM bounded context.

The external subject is processed in memory and compared only as a keyed
digest.  Neither this adapter nor its schema stores a raw subject, token, or
external role.  It performs one parameterized ``SELECT`` and is deliberately
separate from provisioning: binding an external identity is an approved,
append-only administrative operation rather than an incidental login effect.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import hashlib
import hmac
import inspect
from typing import Any

from backend.app.platform.oidc import OIDCIdentityBinding


ConnectionFactory = Callable[[], Awaitable[Any]]
_MAX_ISSUER_LENGTH = 512
_MAX_SUBJECT_LENGTH = 256
_ALLOWED_BROWSER_ROLES = frozenset({"user", "librarian", "research_admin"})


class OIDCSubjectHasher:
    """Produce domain-separated, one-way lookup values for an OIDC subject."""

    def __init__(self, pepper: bytes) -> None:
        if len(pepper) < 32:
            raise ValueError("OIDC subject pepper must contain at least 32 bytes")
        self._pepper = bytes(pepper)

    @staticmethod
    def issuer_fingerprint(issuer: str) -> bytes:
        if not isinstance(issuer, str) or not 1 <= len(issuer) <= _MAX_ISSUER_LENGTH:
            raise ValueError("OIDC issuer is outside the mapper boundary")
        return hashlib.sha256(issuer.encode("utf-8")).digest()

    def subject_digest(self, *, issuer: str, subject: str) -> bytes:
        if not isinstance(subject, str) or not 1 <= len(subject) <= _MAX_SUBJECT_LENGTH:
            raise ValueError("OIDC subject is outside the mapper boundary")
        issuer_fingerprint = self.issuer_fingerprint(issuer)
        return hmac.new(
            self._pepper,
            b"libramas:oidc-subject:v1\x00" + issuer_fingerprint + b"\x00" + subject.encode("utf-8"),
            hashlib.sha256,
        ).digest()


class MySQLOIDCIdentityMapper:
    """Resolve an active external binding to active local roles, read-only."""

    def __init__(self, connection_factory: ConnectionFactory, *, hasher: OIDCSubjectHasher) -> None:
        self._connection_factory = connection_factory
        self._hasher = hasher

    async def close(self) -> None:
        close = getattr(self._connection_factory, "close", None)
        if callable(close):
            result = close()
            if inspect.isawaitable(result):
                await result

    async def resolve(self, *, issuer: str, subject: str) -> OIDCIdentityBinding | None:
        issuer_fingerprint = self._hasher.issuer_fingerprint(issuer)
        subject_digest = self._hasher.subject_digest(issuer=issuer, subject=subject)
        connection = await self._connection_factory()
        try:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "SELECT account.user_id, account.auth_version, account.role_version, role.role_code "
                    "FROM iam_oidc_identity_binding AS binding "
                    "INNER JOIN iam_user_account AS account ON account.user_id = binding.user_id "
                    "INNER JOIN iam_effective_user_role_v AS effective ON effective.user_id = account.user_id "
                    "INNER JOIN iam_role AS role ON role.role_id = effective.role_id "
                    "WHERE binding.issuer_sha256 = %s AND binding.subject_hash = %s "
                    "AND binding.status = 'ACTIVE' AND account.status = 'ACTIVE' "
                    "AND account.account_kind = 'HUMAN' "
                    "ORDER BY role.role_code ASC LIMIT 4",
                    (issuer_fingerprint, subject_digest),
                )
                rows = await cursor.fetchall()
            if not rows:
                return None
            user_id, auth_version, role_version = (int(rows[0][0]), int(rows[0][1]), int(rows[0][2]))
            if any((int(row[0]), int(row[1]), int(row[2])) != (user_id, auth_version, role_version) for row in rows):
                return None
            roles = frozenset(str(row[3]) for row in rows)
            if not roles or not roles.issubset(_ALLOWED_BROWSER_ROLES):
                return None
            return OIDCIdentityBinding(
                user_id=user_id,
                roles=roles,
                auth_version=auth_version,
                role_version=role_version,
            )
        finally:
            connection.close()


__all__ = ["MySQLOIDCIdentityMapper", "OIDCSubjectHasher"]
