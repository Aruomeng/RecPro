from __future__ import annotations

from datetime import UTC, datetime
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app.config import AppSettings
from backend.app.identity.application import IdentityService
from backend.app.identity.domain import (
    AccountKind,
    AccountStatus,
    IdentifierType,
    LoginIdentifier,
    PasswordCredential,
    RoleAction,
    RoleCode,
    UserAccount,
    UserRoleFact,
)
from backend.app.identity.memory import InMemoryIdentityRepository
from backend.app.identity.security import (
    Argon2idPasswordService,
    HMACIdentifierService,
    HMACSecretTokenService,
    LocalJWTIssuer,
)
from backend.app.main import create_app
from backend.app.platform.auth import HMACBearerTokenResolver


class IdentityAPITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.now = datetime(2026, 8, 21, 8, 0, tzinfo=UTC)
        self.passwords = Argon2idPasswordService()
        self.identifiers = HMACIdentifierService(b"i" * 32)
        self.repo = InMemoryIdentityRepository(first_user_id=10_000)
        self.jwt_secret = b"j" * 32
        self.service = IdentityService(
            repository=self.repo, passwords=self.passwords,
            identifiers=self.identifiers, secrets=HMACSecretTokenService(b"t" * 32),
            access_tokens=LocalJWTIssuer(secret=self.jwt_secret, clock=lambda: self.now),
            clock=lambda: self.now,
        )
        self._seed_librarian()
        admin_login = await self.service.login(
            identifier_type=IdentifierType.READER_NUMBER,
            identifier="STAFF-9001", password="Librarian-Pass-2026",
            device_type="BROWSER",
        )
        self.admin_token = admin_login.access_token
        resolver = HMACBearerTokenResolver(
            secret=self.jwt_secret, issuer="libramas-local", audience="libramas-api",
            clock=lambda: self.now.timestamp(),
        )
        settings = AppSettings(
            app_env="test", mysql_password="isolated-test-password",
            auth_cookie_secure=False,
        )
        self.app = create_app(
            settings=settings, identity_service=self.service,
            identity_api_enabled=True, principal_resolver=resolver,
        )

    def _seed_librarian(self) -> None:
        user_id = 9001
        account = UserAccount(
            user_id=user_id, account_uuid=uuid4(), display_name="测试馆员",
            account_kind=AccountKind.HUMAN, status=AccountStatus.ACTIVE,
            auth_version=1, role_version=1, must_change_password=False,
            failed_login_count=0, locked_until=None, last_login_at=None,
            disabled_reason=None, created_by_user_id=None,
            created_at=self.now, updated_at=self.now,
        )
        digest = self.identifiers.digest(
            self.identifiers.normalize(IdentifierType.READER_NUMBER, "STAFF-9001"),
        )
        self.repo.accounts[user_id] = account
        self.repo.identifiers[(IdentifierType.READER_NUMBER, digest)] = LoginIdentifier(
            identifier_id=1, user_id=user_id,
            identifier_type=IdentifierType.READER_NUMBER, identifier_hash=digest,
            display_suffix="AFF-9001", normalization_version="reader-id-nfkc-upper-v1",
            status="ACTIVE", created_at=self.now,
        )
        encoded = self.passwords.hash("Librarian-Pass-2026")
        self.repo.credentials[user_id] = PasswordCredential(
            user_id=user_id, password_hash=encoded, algorithm="ARGON2ID",
            parameters_version="argon2id-v1", password_version=1,
            changed_at=self.now, expires_at=None, updated_at=self.now,
        )
        for role in (RoleCode.USER, RoleCode.LIBRARIAN):
            self.repo.role_facts.append(UserRoleFact(
                fact_uuid=uuid4(), user_id=user_id, role=role, role_version=1,
                action=RoleAction.GRANT, actor_user_id=user_id,
                reason_code="TEST_BOOTSTRAP", idempotency_key=f"test:{role.value}",
                occurred_at=self.now,
            ))

    def test_default_application_does_not_mount_identity(self) -> None:
        default = create_app(settings=AppSettings(mysql_password="isolated-test-password"))
        with TestClient(default) as client:
            self.assertEqual(404, client.post("/api/v1/auth/login", json={}).status_code)

    def test_reader_creation_activation_login_consent_refresh_and_logout(self) -> None:
        with TestClient(self.app) as client:
            created = client.post(
                "/api/v1/admin/users",
                headers={
                    "Authorization": f"Bearer {self.admin_token}",
                    "Idempotency-Key": "reader-create-10000",
                },
                json={
                    "display_name": "真实测试读者",
                    "identifier_type": "READER_NUMBER",
                    "identifier": "READER-10000",
                },
            )
            self.assertEqual(201, created.status_code, created.text)
            body = created.json()
            self.assertEqual(10_000, body["user"]["user_id"])
            self.assertTrue(body["displayed_once"])
            activation_code = body["one_time_code"]

            replay = client.post(
                "/api/v1/admin/users",
                headers={
                    "Authorization": f"Bearer {self.admin_token}",
                    "Idempotency-Key": "reader-create-10000",
                },
                json={
                    "display_name": "真实测试读者",
                    "identifier_type": "READER_NUMBER",
                    "identifier": "READER-10000",
                },
            )
            self.assertEqual(409, replay.status_code)
            self.assertNotIn(activation_code, replay.text)

            activated = client.post("/api/v1/auth/activate", json={
                "identifier_type": "READER_NUMBER", "identifier": "READER-10000",
                "activation_code": activation_code, "new_password": "Reader-Pass-2026",
            })
            self.assertEqual(200, activated.status_code, activated.text)

            logged_in = client.post("/api/v1/auth/login", json={
                "identifier_type": "READER_NUMBER", "identifier": "READER-10000",
                "password": "Reader-Pass-2026", "device_type": "KIOSK",
            })
            self.assertEqual(200, logged_in.status_code, logged_in.text)
            login_body = logged_in.json()
            reader_token = login_body["access_token"]
            self.assertNotIn("recpro_refresh", login_body)
            self.assertIn("recpro_refresh", client.cookies)
            self.assertIn("recpro_csrf", client.cookies)

            me = client.get(
                "/api/v1/auth/me", headers={"Authorization": f"Bearer {reader_token}"},
            )
            self.assertEqual(200, me.status_code, me.text)
            self.assertIn("recommendation.self.execute", me.json()["permissions"])

            consent = client.post(
                "/api/v1/me/personalization-consents",
                headers={"Authorization": f"Bearer {reader_token}"},
                json={
                    "scope": "PERSONALIZED_RECOMMENDATION", "action": "GRANT",
                    "policy_version": "privacy-v1", "source": "LOGIN_ONBOARDING",
                },
            )
            self.assertEqual(200, consent.status_code, consent.text)
            self.assertTrue(
                consent.json()["personalization_consents"]["PERSONALIZED_RECOMMENDATION"],
            )

            rejected_refresh = client.post("/api/v1/auth/refresh")
            self.assertEqual(401, rejected_refresh.status_code)
            refreshed = client.post(
                "/api/v1/auth/refresh",
                headers={"X-CSRF-Token": client.cookies["recpro_csrf"]},
            )
            self.assertEqual(200, refreshed.status_code, refreshed.text)
            refreshed_token = refreshed.json()["access_token"]
            logged_out = client.post(
                "/api/v1/auth/logout",
                headers={"Authorization": f"Bearer {refreshed_token}"},
            )
            self.assertEqual(204, logged_out.status_code, logged_out.text)
            self.assertNotIn("recpro_refresh", client.cookies)

    def test_login_failure_is_generic_and_contains_no_identifier(self) -> None:
        with TestClient(self.app) as client:
            response = client.post("/api/v1/auth/login", json={
                "identifier_type": "READER_NUMBER", "identifier": "UNKNOWN-123",
                "password": "Unknown-Pass-2026", "device_type": "KIOSK",
            })
        self.assertEqual(401, response.status_code)
        self.assertNotIn("UNKNOWN-123", response.text)
        self.assertNotIn("Unknown-Pass", response.text)


if __name__ == "__main__":
    unittest.main()
