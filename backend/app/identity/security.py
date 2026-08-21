"""Cryptographic adapters for local IAM; raw secrets never enter domain facts."""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
import re
import secrets
import unicodedata
from typing import Callable
from uuid import UUID, uuid4

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.low_level import Type

from backend.app.identity.domain import IdentifierType, RoleCode, UserAccount
from backend.app.identity.application import IdentityService
from backend.app.shared_kernel.contracts.auth import AuthenticatedPrincipal


_IDENTIFIER = re.compile(r"^[A-Z0-9._-]{3,64}$")


class Argon2idPasswordService:
    parameters_version = "argon2id-v1"

    def __init__(self) -> None:
        self._hasher = PasswordHasher(
            time_cost=3, memory_cost=65_536, parallelism=2,
            hash_len=32, salt_len=16, type=Type.ID,
        )
        self._dummy = self._hasher.hash("LibraMAS-unknown-account-dummy")

    @staticmethod
    def _validate(password: str) -> str:
        if not isinstance(password, str) or not 10 <= len(password) <= 128:
            raise ValueError("password must contain 10-128 characters")
        if any(ord(character) < 32 for character in password):
            raise ValueError("password must not contain control characters")
        return password

    def hash(self, password: str) -> str:
        return self._hasher.hash(self._validate(password))

    def verify(self, encoded: str, password: str) -> bool:
        try:
            candidate = self._validate(password)
        except ValueError:
            candidate = "LibraMAS-invalid-password-padding"
        try:
            return bool(self._hasher.verify(encoded, candidate))
        except (InvalidHashError, VerificationError):
            return False

    def burn_unknown(self, password: str) -> None:
        self.verify(self._dummy, password)


class HMACIdentifierService:
    normalization_version = "reader-id-nfkc-upper-v1"

    def __init__(self, pepper: bytes) -> None:
        if len(pepper) < 32:
            raise ValueError("identifier pepper must contain at least 32 bytes")
        self._pepper = bytes(pepper)

    def normalize(self, identifier_type: IdentifierType, value: str) -> str:
        del identifier_type
        normalized = unicodedata.normalize("NFKC", value).strip().upper()
        if _IDENTIFIER.fullmatch(normalized) is None:
            raise ValueError("identifier contains unsupported characters or length")
        return normalized

    def digest(self, normalized: str) -> bytes:
        return hmac.new(self._pepper, normalized.encode(), hashlib.sha256).digest()


class HMACSecretTokenService:
    def __init__(self, pepper: bytes, *, token_bytes: int = 32) -> None:
        if len(pepper) < 32 or token_bytes < 16:
            raise ValueError("token pepper and entropy are below the security boundary")
        self._pepper = bytes(pepper)
        self._token_bytes = token_bytes

    def generate(self) -> str:
        return secrets.token_urlsafe(self._token_bytes)

    def digest(self, token: str) -> bytes:
        if not isinstance(token, str) or not 16 <= len(token) <= 256:
            return hmac.new(self._pepper, b"invalid-token", hashlib.sha256).digest()
        return hmac.new(self._pepper, token.encode(), hashlib.sha256).digest()


class LocalJWTIssuer:
    """Issue short-lived HS256 access tokens compatible with the existing resolver."""

    def __init__(
        self, *, secret: bytes, issuer: str = "libramas-local",
        audience: str = "libramas-api", ttl_seconds: int = 600,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if len(secret) < 32 or not issuer or not audience or not 60 <= ttl_seconds <= 3600:
            raise ValueError("JWT issuer configuration is outside the local IAM boundary")
        self._secret = bytes(secret)
        self._issuer = issuer
        self._audience = audience
        self._ttl_seconds = ttl_seconds
        self._clock = clock

    @staticmethod
    def _segment(value: object) -> str:
        raw = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    def issue(
        self, *, account: UserAccount, roles: frozenset[RoleCode], session_id: UUID,
    ) -> tuple[str, int]:
        now = self._clock().astimezone(UTC)
        payload = {
            "iss": self._issuer,
            "aud": self._audience,
            "sub": str(account.user_id),
            "roles": sorted(role.value for role in roles),
            "sid": str(session_id),
            "av": account.auth_version,
            "rv": account.role_version,
            "iat": int(now.timestamp()),
            "nbf": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=self._ttl_seconds)).timestamp()),
            "jti": str(uuid4()),
        }
        header = self._segment({"alg": "HS256", "typ": "JWT"})
        body = self._segment(payload)
        signature = hmac.new(self._secret, f"{header}.{body}".encode(), hashlib.sha256).digest()
        encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
        return f"{header}.{body}.{encoded_signature}", self._ttl_seconds


class VersionedPrincipalResolver:
    """Fail closed unless both JWT and mutable account/session state are valid."""

    def __init__(self, token_resolver: object, identity_service: IdentityService) -> None:
        self._token_resolver = token_resolver
        self._identity_service = identity_service

    async def __call__(self, token: str) -> AuthenticatedPrincipal | None:
        candidate = self._token_resolver(token)  # type: ignore[operator]
        if not isinstance(candidate, AuthenticatedPrincipal):
            return None
        try:
            return await self._identity_service.validate_principal(candidate)
        except Exception:
            return None


__all__ = [
    "Argon2idPasswordService", "HMACIdentifierService", "HMACSecretTokenService",
    "LocalJWTIssuer", "VersionedPrincipalResolver",
]
