"""Strict HS256 bearer-token verification for the explicit formal runtime.

The HTTP adapters only receive :class:`AuthenticatedPrincipal` instances.  This
module is the platform-side implementation of that boundary: it verifies a
compact JWT using one explicitly supplied secret, validates the issuer,
audience, time claims and role vocabulary, and never returns token material to
application code.  A deployment that uses an external OIDC/JWKS provider can
replace this adapter at the composition root without changing API or domain
code.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import hmac
import json
import math
import re
import time
from typing import Any, Callable
from uuid import UUID

from backend.app.config import AppSettings
from backend.app.shared_kernel.contracts.auth import AuthenticatedPrincipal


_BASE64URL = re.compile(r"^[A-Za-z0-9_-]+$")
_SUBJECT = re.compile(r"^[1-9][0-9]{0,18}$")
_ALLOWED_ROLES = frozenset({"user", "librarian", "research_admin", "service_worker"})
_MAX_TOKEN_LENGTH = 16 * 1024
_MAX_SEGMENT_LENGTH = 8 * 1024


def _decode_json_segment(segment: str) -> dict[str, Any] | None:
    if (
        not isinstance(segment, str)
        or not segment
        or len(segment) > _MAX_SEGMENT_LENGTH
        or _BASE64URL.fullmatch(segment) is None
    ):
        return None
    padding = "=" * ((-len(segment)) % 4)
    try:
        decoded = base64.urlsafe_b64decode(segment + padding)
    except (binascii.Error, ValueError):
        return None
    if (
        not decoded
        or len(decoded) > _MAX_SEGMENT_LENGTH
        or base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii")
        != segment
    ):
        return None
    try:
        payload = json.loads(decoded.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _numeric_claim(payload: dict[str, Any], name: str, *, required: bool) -> float | None:
    value = payload.get(name)
    if value is None:
        return None if not required else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


@dataclass(frozen=True, slots=True)
class HMACBearerTokenResolver:
    """Callable HS256 verifier returning an application identity or ``None``."""

    secret: bytes
    issuer: str
    audience: str
    clock_skew_seconds: int = 30
    clock: Callable[[], float] = time.time

    def __post_init__(self) -> None:
        if len(self.secret) < 32:
            raise ValueError("HS256 secret must contain at least 32 bytes")
        if not self.issuer or not self.audience:
            raise ValueError("issuer and audience must be non-blank")
        if not 0 <= self.clock_skew_seconds <= 300:
            raise ValueError("clock skew must be between 0 and 300 seconds")

    def __call__(self, token: str) -> AuthenticatedPrincipal | None:
        if not isinstance(token, str) or not 1 <= len(token) <= _MAX_TOKEN_LENGTH:
            return None
        try:
            header_segment, payload_segment, signature_segment = token.split(".")
            signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
            signature = base64.urlsafe_b64decode(
                signature_segment + "=" * ((-len(signature_segment)) % 4)
            )
        except (ValueError, UnicodeEncodeError, binascii.Error):
            return None
        if (
            not _BASE64URL.fullmatch(signature_segment)
            or len(signature) != hashlib.sha256().digest_size
        ):
            return None

        expected = hmac.new(self.secret, signing_input, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, signature):
            return None

        header = _decode_json_segment(header_segment)
        payload = _decode_json_segment(payload_segment)
        if header is None or payload is None:
            return None
        if header.get("alg") != "HS256" or header.get("typ") != "JWT":
            return None
        if payload.get("iss") != self.issuer:
            return None

        audience = payload.get("aud")
        if isinstance(audience, str):
            audiences = {audience}
        elif isinstance(audience, list) and all(isinstance(item, str) for item in audience):
            audiences = set(audience)
        else:
            return None
        if self.audience not in audiences:
            return None

        subject = payload.get("sub")
        if not isinstance(subject, str) or _SUBJECT.fullmatch(subject) is None:
            return None
        user_id = int(subject)

        roles = payload.get("roles")
        if (
            not isinstance(roles, list)
            or not roles
            or not all(isinstance(role, str) and role in _ALLOWED_ROLES for role in roles)
        ):
            return None

        expiration = _numeric_claim(payload, "exp", required=True)
        if expiration is None:
            return None
        now = self.clock()
        skew = float(self.clock_skew_seconds)
        if not math.isfinite(now) or now > expiration + skew:
            return None

        not_before = _numeric_claim(payload, "nbf", required=False)
        if payload.get("nbf") is not None and not_before is None:
            return None
        if not_before is not None and now + skew < not_before:
            return None

        issued_at = _numeric_claim(payload, "iat", required=False)
        if payload.get("iat") is not None and issued_at is None:
            return None
        if issued_at is not None and issued_at > now + skew:
            return None
        if issued_at is not None and expiration < issued_at:
            return None

        token_id = payload.get("jti")
        if token_id is not None and (
            not isinstance(token_id, str) or not 1 <= len(token_id) <= 128
        ):
            return None
        session_id = payload.get("sid")
        try:
            parsed_session_id = UUID(session_id) if session_id is not None else None
        except (TypeError, ValueError):
            return None
        auth_version = payload.get("av")
        role_version = payload.get("rv")
        if auth_version is not None and (
            isinstance(auth_version, bool) or not isinstance(auth_version, int) or auth_version < 1
        ):
            return None
        if role_version is not None and (
            isinstance(role_version, bool) or not isinstance(role_version, int) or role_version < 1
        ):
            return None
        return AuthenticatedPrincipal(
            user_id=user_id,
            roles=frozenset(roles),
            token_id=token_id,
            session_id=parsed_session_id,
            auth_version=auth_version,
            role_version=role_version,
            expires_at=datetime.fromtimestamp(expiration, tz=UTC),
        )


def build_formal_principal_resolver(
    settings: AppSettings,
) -> HMACBearerTokenResolver | None:
    """Build the configured resolver, or ``None`` while auth is disabled."""

    if not settings.auth_enabled:
        return None
    if settings.auth_jwt_secret is None:
        raise ValueError("formal authentication requires an HS256 secret")
    return HMACBearerTokenResolver(
        secret=settings.auth_jwt_secret.get_secret_value().encode("utf-8"),
        issuer=settings.auth_jwt_issuer,
        audience=settings.auth_jwt_audience,
        clock_skew_seconds=settings.auth_clock_skew_seconds,
    )


__all__ = ["HMACBearerTokenResolver", "build_formal_principal_resolver"]
