"""Fail-closed OIDC/JWKS bearer verification.

The local IAM path uses :mod:`backend.app.platform.auth` and remains the
default research mode.  This module is an independently injectable production
adapter: it verifies an asymmetric JWT against a bounded, expiring JWKS cache
and then asks a local identity-mapping port for the account and roles.  Roles
are never trusted from the external token.

There is intentionally no HTTP client construction here.  A deployment must
provide a bounded async JWKS fetcher and an identity mapper at its composition
root, where TLS, proxy, timeout and database policies can be reviewed
separately.
"""

from __future__ import annotations

import base64
import binascii
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
import inspect
import json
import math
import time
from typing import Any, Awaitable, Callable, Mapping, Protocol
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from backend.app.shared_kernel.contracts.auth import AuthenticatedPrincipal


_ALLOWED_ALGORITHMS = frozenset({"RS256", "PS256", "ES256"})
_ALLOWED_ROLES = frozenset({"user", "librarian", "research_admin", "service_worker"})
_MAX_TOKEN_LENGTH = 16 * 1024
_MAX_SEGMENT_LENGTH = 8 * 1024
_MAX_KID_LENGTH = 128
_MAX_SUBJECT_LENGTH = 256
_MAX_JWKS_KEYS = 32
_BASE64URL_ALPHABET = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-")


def _decode_base64url(value: object, *, maximum: int) -> bytes | None:
    if not isinstance(value, str) or not 1 <= len(value) <= maximum:
        return None
    if any(char not in _BASE64URL_ALPHABET for char in value):
        return None
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * ((-len(value)) % 4))
    except (binascii.Error, ValueError):
        return None
    if not decoded or len(decoded) > maximum:
        return None
    canonical = base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii")
    return decoded if canonical == value else None


def _decode_json_segment(segment: str) -> dict[str, Any] | None:
    raw = _decode_base64url(segment, maximum=_MAX_SEGMENT_LENGTH)
    if raw is None:
        return None
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _numeric_claim(payload: Mapping[str, object], name: str) -> float | None:
    value = payload.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


@dataclass(frozen=True, slots=True)
class OIDCIdentityBinding:
    """Local account projection returned by the external-subject mapper."""

    user_id: int
    roles: frozenset[str]
    session_id: UUID | None = None
    auth_version: int | None = None
    role_version: int | None = None

    def __post_init__(self) -> None:
        if isinstance(self.user_id, bool) or self.user_id < 1:
            raise ValueError("OIDC mapping user_id must be positive")
        if not self.roles or not self.roles.issubset(_ALLOWED_ROLES):
            raise ValueError("OIDC mapping contains an unsupported role")
        if "service_worker" in self.roles:
            raise ValueError("service_worker cannot be mapped to a browser identity")
        for name in ("auth_version", "role_version"):
            value = getattr(self, name)
            if value is not None and (isinstance(value, bool) or value < 1):
                raise ValueError(f"{name} must be positive when present")


class OIDCIdentityMapper(Protocol):
    async def resolve(self, *, issuer: str, subject: str) -> OIDCIdentityBinding | None: ...


JWKSFetcher = Callable[[], Mapping[str, object] | Awaitable[Mapping[str, object]]]


@dataclass(frozen=True, slots=True)
class _VerifiedKey:
    kid: str
    algorithm: str
    key: object


class JWKSCache:
    """Bounded async JWKS cache with one refresh for an unknown ``kid``.

    A stale cache is never used after refresh failure.  Unknown-key refreshes
    are rate-limited for a short interval to avoid turning arbitrary ``kid``
    values into an unbounded remote fetch loop.
    """

    def __init__(
        self,
        fetcher: JWKSFetcher,
        *,
        ttl_seconds: int = 15 * 60,
        unknown_kid_refresh_cooldown_seconds: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not callable(fetcher):
            raise ValueError("JWKS fetcher must be callable")
        if not 60 <= ttl_seconds <= 24 * 60 * 60:
            raise ValueError("JWKS cache TTL is outside the safe bound")
        if not 0 <= unknown_kid_refresh_cooldown_seconds <= 60:
            raise ValueError("JWKS unknown-kid cooldown is outside the safe bound")
        self._fetcher = fetcher
        self._ttl_seconds = ttl_seconds
        self._unknown_kid_cooldown = unknown_kid_refresh_cooldown_seconds
        self._clock = clock
        self._keys: dict[str, _VerifiedKey] = {}
        self._loaded_at: float | None = None
        self._last_forced_refresh_at: float | None = None
        self._refresh_lock = asyncio.Lock()

    async def get(self, kid: str) -> _VerifiedKey | None:
        if not isinstance(kid, str) or not 1 <= len(kid) <= _MAX_KID_LENGTH:
            return None
        now = self._clock()
        if self._is_fresh(now) and kid in self._keys:
            return self._keys[kid]
        async with self._refresh_lock:
            now = self._clock()
            if self._is_fresh(now) and kid in self._keys:
                return self._keys[kid]
            force_refresh = kid not in self._keys
            if force_refresh and self._last_forced_refresh_at is not None:
                if now - self._last_forced_refresh_at < self._unknown_kid_cooldown:
                    return None
            if force_refresh:
                self._last_forced_refresh_at = now
            try:
                result = self._fetcher()
                document = await result if inspect.isawaitable(result) else result
                keys = _parse_jwks(document)
            except Exception:
                # Do not retain stale keys after a refresh was required.  This
                # makes JWKS outage and key rotation fail closed.
                self._keys = {}
                self._loaded_at = None
                return None
            self._keys = {item.kid: item for item in keys}
            self._loaded_at = now
            return self._keys.get(kid)

    def _is_fresh(self, now: float) -> bool:
        return (
            math.isfinite(now)
            and self._loaded_at is not None
            and now - self._loaded_at < self._ttl_seconds
        )


def _parse_jwks(document: object) -> tuple[_VerifiedKey, ...]:
    if not isinstance(document, Mapping) or set(document) - {"keys"}:
        raise ValueError("JWKS document contains unsupported fields")
    raw_keys = document.get("keys")
    if not isinstance(raw_keys, list) or not 1 <= len(raw_keys) <= _MAX_JWKS_KEYS:
        raise ValueError("JWKS key set is outside the bound")
    parsed: list[_VerifiedKey] = []
    seen: set[str] = set()
    for raw in raw_keys:
        if not isinstance(raw, Mapping):
            raise ValueError("JWKS key is not an object")
        kid = raw.get("kid")
        alg = raw.get("alg")
        if (
            not isinstance(kid, str)
            or not 1 <= len(kid) <= _MAX_KID_LENGTH
            or kid in seen
            or not isinstance(alg, str)
            or alg not in _ALLOWED_ALGORITHMS
        ):
            raise ValueError("JWKS key identity or algorithm is invalid")
        if raw.get("use") not in (None, "sig"):
            raise ValueError("JWKS key use is not signing")
        key_ops = raw.get("key_ops")
        if key_ops is not None and (not isinstance(key_ops, list) or "verify" not in key_ops):
            raise ValueError("JWKS key cannot verify signatures")
        key = _public_key(raw, alg)
        parsed.append(_VerifiedKey(kid, alg, key))
        seen.add(kid)
    return tuple(parsed)


def _public_key(jwk: Mapping[str, object], algorithm: str) -> object:
    kty = jwk.get("kty")
    if algorithm in {"RS256", "PS256"} and kty == "RSA":
        modulus = _decode_base64url(jwk.get("n"), maximum=1024)
        exponent = _decode_base64url(jwk.get("e"), maximum=16)
        if modulus is None or exponent is None:
            raise ValueError("RSA JWK parameters are invalid")
        key = rsa.RSAPublicNumbers(int.from_bytes(exponent, "big"), int.from_bytes(modulus, "big")).public_key()
        if key.key_size < 2048:
            raise ValueError("RSA JWK key is below 2048 bits")
        return key
    if algorithm == "ES256" and kty == "EC" and jwk.get("crv") == "P-256":
        x = _decode_base64url(jwk.get("x"), maximum=64)
        y = _decode_base64url(jwk.get("y"), maximum=64)
        if x is None or y is None or len(x) != 32 or len(y) != 32:
            raise ValueError("EC JWK coordinates are invalid")
        return ec.EllipticCurvePublicNumbers(
            int.from_bytes(x, "big"), int.from_bytes(y, "big"), ec.SECP256R1()
        ).public_key()
    raise ValueError("JWKS key type does not match the allow-listed algorithm")


def _verify_signature(key: _VerifiedKey, signing_input: bytes, signature: bytes) -> bool:
    try:
        if key.algorithm == "RS256":
            assert isinstance(key.key, rsa.RSAPublicKey)
            key.key.verify(signature, signing_input, padding.PKCS1v15(), hashes.SHA256())
        elif key.algorithm == "PS256":
            assert isinstance(key.key, rsa.RSAPublicKey)
            key.key.verify(
                signature, signing_input,
                padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=hashes.SHA256().digest_size),
                hashes.SHA256(),
            )
        else:
            assert isinstance(key.key, ec.EllipticCurvePublicKey)
            if len(signature) != 64:
                return False
            der_signature = encode_dss_signature(
                int.from_bytes(signature[:32], "big"), int.from_bytes(signature[32:], "big")
            )
            key.key.verify(der_signature, signing_input, ec.ECDSA(hashes.SHA256()))
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


class OIDCBearerTokenResolver:
    """Async OIDC resolver returning only locally mapped principals."""

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        jwks: JWKSCache,
        identity_mapper: OIDCIdentityMapper,
        clock: Callable[[], float] = time.time,
        clock_skew_seconds: int = 30,
    ) -> None:
        if not issuer.strip() or not audience.strip():
            raise ValueError("OIDC issuer and audience must be non-blank")
        if not 0 <= clock_skew_seconds <= 300:
            raise ValueError("OIDC clock skew must be between 0 and 300 seconds")
        self._issuer = issuer
        self._audience = audience
        self._jwks = jwks
        self._identity_mapper = identity_mapper
        self._clock = clock
        self._clock_skew = float(clock_skew_seconds)

    async def __call__(self, token: str) -> AuthenticatedPrincipal | None:
        if not isinstance(token, str) or not 1 <= len(token) <= _MAX_TOKEN_LENGTH:
            return None
        parts = token.split(".")
        if len(parts) != 3 or any(not 1 <= len(part) <= _MAX_SEGMENT_LENGTH for part in parts):
            return None
        header_segment, payload_segment, signature_segment = parts
        header = _decode_json_segment(header_segment)
        payload = _decode_json_segment(payload_segment)
        signature = _decode_base64url(signature_segment, maximum=1024)
        if header is None or payload is None or signature is None:
            return None
        if (
            header.get("typ") != "JWT"
            or header.get("alg") not in _ALLOWED_ALGORITHMS
            or not isinstance(header.get("kid"), str)
            or not 1 <= len(header["kid"]) <= _MAX_KID_LENGTH
            or "crit" in header
        ):
            return None
        kid = header["kid"]
        key = await self._jwks.get(kid)
        if key is None or key.algorithm != header["alg"]:
            return None
        if not _verify_signature(key, f"{header_segment}.{payload_segment}".encode("ascii"), signature):
            return None
        if payload.get("iss") != self._issuer:
            return None
        if not self._valid_audience(payload):
            return None
        subject = payload.get("sub")
        if not isinstance(subject, str) or not 1 <= len(subject) <= _MAX_SUBJECT_LENGTH:
            return None
        expiration = _numeric_claim(payload, "exp")
        issued_at = _numeric_claim(payload, "iat")
        if expiration is None or issued_at is None:
            return None
        now = self._clock()
        if not math.isfinite(now) or now > expiration + self._clock_skew:
            return None
        if issued_at > now + self._clock_skew or expiration < issued_at:
            return None
        not_before = _numeric_claim(payload, "nbf") if payload.get("nbf") is not None else None
        if payload.get("nbf") is not None and not_before is None:
            return None
        if not_before is not None and now + self._clock_skew < not_before:
            return None
        token_id = payload.get("jti")
        if token_id is not None and (not isinstance(token_id, str) or not 1 <= len(token_id) <= 128):
            return None
        try:
            mapped = self._identity_mapper.resolve(issuer=self._issuer, subject=subject)
            binding = await mapped if inspect.isawaitable(mapped) else mapped
            if binding is None or not isinstance(binding, OIDCIdentityBinding):
                return None
            return AuthenticatedPrincipal(
                user_id=binding.user_id,
                roles=binding.roles,
                token_id=token_id,
                session_id=binding.session_id,
                auth_version=binding.auth_version,
                role_version=binding.role_version,
                expires_at=datetime.fromtimestamp(expiration, tz=UTC),
            )
        except Exception:
            return None

    def _valid_audience(self, payload: Mapping[str, object]) -> bool:
        audience = payload.get("aud")
        if isinstance(audience, str):
            return audience == self._audience
        if not isinstance(audience, list) or not audience or not all(isinstance(item, str) for item in audience):
            return False
        if self._audience not in audience:
            return False
        if len(audience) > 1 and payload.get("azp") != self._audience:
            return False
        return True


__all__ = [
    "JWKSCache",
    "OIDCBearerTokenResolver",
    "OIDCIdentityBinding",
    "OIDCIdentityMapper",
]
