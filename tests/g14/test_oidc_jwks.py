from __future__ import annotations

import base64
import json
import unittest
from uuid import uuid4

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from backend.app.platform.oidc import (
    JWKSCache,
    OIDCBearerTokenResolver,
    OIDCIdentityBinding,
)
from backend.app.config import AppSettings


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _segment(value: object) -> str:
    return _b64(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


class _Mapper:
    def __init__(self, binding: OIDCIdentityBinding | None) -> None:
        self.binding = binding
        self.calls: list[tuple[str, str]] = []

    async def resolve(self, *, issuer: str, subject: str) -> OIDCIdentityBinding | None:
        self.calls.append((issuer, subject))
        return self.binding


class OIDCJWKSTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public = self.key.public_key().public_numbers()
        self.jwk = {
            "kty": "RSA",
            "kid": "research-key-1",
            "alg": "RS256",
            "use": "sig",
            "n": _b64(public.n.to_bytes((public.n.bit_length() + 7) // 8, "big")),
            "e": _b64(public.e.to_bytes((public.e.bit_length() + 7) // 8, "big")),
        }
        self.now = 1_800_000_000.0

    def _token(self, **claims: object) -> str:
        header = _segment({"alg": "RS256", "kid": "research-key-1", "typ": "JWT"})
        payload = {
            "iss": "https://id.example.edu",
            "aud": "libramas-api",
            "sub": "oidc-subject-42",
            "iat": self.now - 30,
            "nbf": self.now - 30,
            "exp": self.now + 300,
            "jti": str(uuid4()),
        }
        payload.update(claims)
        body = _segment(payload)
        signature = self.key.sign(
            f"{header}.{body}".encode("ascii"), padding.PKCS1v15(), hashes.SHA256()
        )
        return f"{header}.{body}.{_b64(signature)}"

    async def test_valid_token_uses_local_mapping_and_never_token_roles(self) -> None:
        calls = 0

        async def fetch() -> dict[str, object]:
            nonlocal calls
            calls += 1
            return {"keys": [self.jwk]}

        mapper = _Mapper(OIDCIdentityBinding(10001, frozenset({"user"})))
        resolver = OIDCBearerTokenResolver(
            issuer="https://id.example.edu",
            audience="libramas-api",
            jwks=JWKSCache(fetch, clock=lambda: self.now),
            identity_mapper=mapper,
            clock=lambda: self.now,
        )
        token = self._token(roles=["research_admin"])
        principal = await resolver(token)
        self.assertIsNotNone(principal)
        self.assertEqual(10001, principal.user_id)
        self.assertEqual(frozenset({"user"}), principal.roles)
        self.assertEqual([("https://id.example.edu", "oidc-subject-42")], mapper.calls)
        self.assertEqual(1, calls)

    async def test_unknown_kid_refreshes_once_then_fails_closed(self) -> None:
        calls = 0

        async def fetch() -> dict[str, object]:
            nonlocal calls
            calls += 1
            return {"keys": [self.jwk]}

        cache = JWKSCache(fetch, unknown_kid_refresh_cooldown_seconds=60, clock=lambda: self.now)
        self.assertIsNone(await cache.get("unknown-kid"))
        self.assertIsNone(await cache.get("unknown-kid"))
        self.assertEqual(1, calls)

    async def test_expired_or_invalid_audience_is_rejected_before_mapping(self) -> None:
        async def fetch() -> dict[str, object]:
            return {"keys": [self.jwk]}

        mapper = _Mapper(OIDCIdentityBinding(10001, frozenset({"user"})))
        resolver = OIDCBearerTokenResolver(
            issuer="https://id.example.edu", audience="libramas-api",
            jwks=JWKSCache(fetch, clock=lambda: self.now), identity_mapper=mapper,
            clock=lambda: self.now,
        )
        self.assertIsNone(await resolver(self._token(exp=self.now - 31)))
        self.assertIsNone(await resolver(self._token(aud=["libramas-api", "other"])))
        self.assertEqual([], mapper.calls)

    async def test_multiple_audience_requires_authorized_party(self) -> None:
        async def fetch() -> dict[str, object]:
            return {"keys": [self.jwk]}

        mapper = _Mapper(OIDCIdentityBinding(10001, frozenset({"user"})))
        resolver = OIDCBearerTokenResolver(
            issuer="https://id.example.edu", audience="libramas-api",
            jwks=JWKSCache(fetch, clock=lambda: self.now), identity_mapper=mapper,
            clock=lambda: self.now,
        )
        self.assertIsNone(await resolver(self._token(aud=["libramas-api", "other"])))
        valid = await resolver(self._token(aud=["libramas-api", "other"], azp="libramas-api"))
        self.assertIsNotNone(valid)

    def test_browser_binding_rejects_service_worker(self) -> None:
        with self.assertRaises(ValueError):
            OIDCIdentityBinding(10001, frozenset({"service_worker"}))

    def test_oidc_mode_requires_explicit_provider_configuration(self) -> None:
        with self.assertRaises(ValueError):
            AppSettings(
                app_env="production",
                mysql_password="isolated-test-password",
                auth_enabled=True,
                auth_mode="oidc",
            )
        settings = AppSettings(
            app_env="production",
            mysql_password="isolated-test-password",
            auth_enabled=True,
            auth_mode="oidc",
            oidc_issuer="https://id.example.edu/",
            oidc_audience="libramas-api",
            oidc_jwks_uri="https://id.example.edu/.well-known/jwks.json",
        )
        self.assertIsNone(settings.auth_jwt_secret)
        self.assertEqual("https://id.example.edu", settings.oidc_issuer)


if __name__ == "__main__":
    unittest.main()
