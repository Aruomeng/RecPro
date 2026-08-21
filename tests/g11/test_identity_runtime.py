from __future__ import annotations

from datetime import UTC, datetime, timedelta
import unittest
from uuid import uuid4

from backend.app.identity.application import IdentityService, consent_evidence_hash
from backend.app.identity.domain import (
    AccountStatus,
    AccountStatusAction,
    ConsentAction,
    ConsentScope,
    IdentifierType,
    IdentityError,
    RoleAction,
    RoleCode,
)
from backend.app.identity.memory import InMemoryIdentityRepository
from backend.app.identity.security import (
    Argon2idPasswordService,
    HMACIdentifierService,
    HMACSecretTokenService,
    LocalJWTIssuer,
)
from backend.app.platform.auth import HMACBearerTokenResolver
from backend.app.shared_kernel.contracts.auth import AuthenticatedPrincipal


class IdentityRuntimeTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.passwords = Argon2idPasswordService()

    def setUp(self) -> None:
        self.now = datetime(2026, 8, 21, 5, 0, tzinfo=UTC)
        self.repo = InMemoryIdentityRepository()
        self.secret = b"j" * 32
        self.service = IdentityService(
            repository=self.repo,
            passwords=self.passwords,
            identifiers=HMACIdentifierService(b"i" * 32),
            secrets=HMACSecretTokenService(b"t" * 32),
            access_tokens=LocalJWTIssuer(secret=self.secret, clock=lambda: self.now),
            clock=lambda: self.now,
        )
        self.librarian = AuthenticatedPrincipal(
            user_id=9001, roles=frozenset({"librarian"}),
        )
        self.admin = AuthenticatedPrincipal(
            user_id=9002, roles=frozenset({"research_admin"}),
        )

    async def provision_and_activate(self, identifier: str = "LIB-2026-0001"):
        provisioned = await self.service.provision_reader(
            display_name="测试读者", identifier_type=IdentifierType.READER_NUMBER,
            identifier=identifier, actor=self.librarian,
            idempotency_key=f"provision-{identifier}",
        )
        self.assertIsNotNone(provisioned.activation_code)
        account = await self.service.activate(
            identifier_type=IdentifierType.READER_NUMBER, identifier=identifier,
            activation_code=str(provisioned.activation_code),
            new_password="Correct-Horse-2026",
        )
        return account

    async def test_real_login_issues_versioned_jwt_and_rotatable_session(self) -> None:
        account = await self.provision_and_activate()
        result = await self.service.login(
            identifier_type=IdentifierType.READER_NUMBER,
            identifier=" lib-2026-0001 ", password="Correct-Horse-2026",
        )
        self.assertEqual(account.user_id, result.account.user_id)
        self.assertEqual(frozenset({RoleCode.USER}), result.roles)
        resolver = HMACBearerTokenResolver(
            secret=self.secret, issuer="libramas-local", audience="libramas-api",
            clock=lambda: self.now.timestamp(),
        )
        principal = resolver(result.access_token)
        self.assertIsNotNone(principal)
        assert principal is not None
        self.assertEqual(result.session_uuid, principal.session_id)
        self.assertEqual(result.account.auth_version, principal.auth_version)
        self.assertEqual(result.account.role_version, principal.role_version)

        refreshed = await self.service.refresh(
            refresh_token=result.refresh_token, csrf_token=result.csrf_token,
        )
        self.assertNotEqual(result.refresh_token, refreshed.refresh_token)
        with self.assertRaisesRegex(IdentityError, "REFRESH_TOKEN_REUSED"):
            await self.service.refresh(
                refresh_token=result.refresh_token, csrf_token=result.csrf_token,
            )
        session = await self.repo.get_session(result.session_uuid)
        self.assertEqual("TOKEN_REUSE", session.revoke_reason if session else None)

    async def test_provisioning_idempotency_never_invents_a_second_activation_code(self) -> None:
        first = await self.service.provision_reader(
            display_name="幂等读者", identifier_type=IdentifierType.STUDENT_NUMBER,
            identifier="S20260002", actor=self.librarian,
            idempotency_key="provision-student-2",
        )
        second = await self.service.provision_reader(
            display_name="幂等读者", identifier_type=IdentifierType.STUDENT_NUMBER,
            identifier="S20260002", actor=self.librarian,
            idempotency_key="provision-student-2",
        )
        self.assertEqual(first.account.user_id, second.account.user_id)
        self.assertFalse(first.replayed)
        self.assertTrue(second.replayed)
        self.assertIsNotNone(first.activation_code)
        self.assertIsNone(second.activation_code)
        self.assertEqual(1, len(self.repo.accounts))

    async def test_five_bad_passwords_lock_without_revealing_credentials(self) -> None:
        account = await self.provision_and_activate("LIB-LOCK-0001")
        for _ in range(5):
            with self.assertRaisesRegex(IdentityError, "INVALID_CREDENTIALS"):
                await self.service.login(
                    identifier_type=IdentifierType.READER_NUMBER,
                    identifier="LIB-LOCK-0001", password="Wrong-Password-2026",
                )
        locked = await self.repo.get_account(account.user_id)
        self.assertEqual(self.now + timedelta(minutes=15), locked.locked_until if locked else None)
        serialised = str(self.repo.security_events)
        self.assertNotIn("Wrong-Password", serialised)
        self.assertNotIn("Correct-Horse", serialised)

    async def test_role_change_is_append_only_and_invalidates_existing_refresh(self) -> None:
        account = await self.provision_and_activate("LIB-ROLE-0001")
        login = await self.service.login(
            identifier_type=IdentifierType.READER_NUMBER,
            identifier="LIB-ROLE-0001", password="Correct-Horse-2026",
        )
        before = len(self.repo.role_facts)
        updated = await self.service.role_action(
            target_user_id=account.user_id, role=RoleCode.LIBRARIAN,
            action=RoleAction.GRANT, actor=self.admin,
            reason_code="APPROVED_STAFF_ROLE", idempotency_key="role-grant-0001",
        )
        self.assertEqual(before + 1, len(self.repo.role_facts))
        self.assertGreater(updated.role_version, login.account.role_version)
        with self.assertRaisesRegex(IdentityError, "REFRESH_TOKEN_INVALID"):
            await self.service.refresh(
                refresh_token=login.refresh_token, csrf_token=login.csrf_token,
            )
        with self.assertRaisesRegex(IdentityError, "SERVICE_ROLE_BROWSER_ASSIGNMENT_FORBIDDEN"):
            await self.service.role_action(
                target_user_id=account.user_id, role=RoleCode.SERVICE_WORKER,
                action=RoleAction.GRANT, actor=self.admin,
                reason_code="NOT_ALLOWED", idempotency_key="role-service-0001",
            )

    async def test_status_action_is_bounded_idempotent_and_revokes_sessions(self) -> None:
        account = await self.provision_and_activate("LIB-STATUS-0001")
        login = await self.service.login(
            identifier_type=IdentifierType.READER_NUMBER,
            identifier="LIB-STATUS-0001", password="Correct-Horse-2026",
        )
        disabled = await self.service.status_action(
            target_user_id=account.user_id, action=AccountStatusAction.DISABLE,
            actor=self.librarian, reason_code="READER_LEFT_LIBRARY",
            idempotency_key="status-disable-0001",
        )
        replayed = await self.service.status_action(
            target_user_id=account.user_id, action=AccountStatusAction.DISABLE,
            actor=self.librarian, reason_code="READER_LEFT_LIBRARY",
            idempotency_key="status-disable-0001",
        )
        self.assertEqual(AccountStatus.DISABLED, disabled.status)
        self.assertEqual(disabled.auth_version, replayed.auth_version)
        with self.assertRaisesRegex(IdentityError, "REFRESH_TOKEN_INVALID"):
            await self.service.refresh(
                refresh_token=login.refresh_token, csrf_token=login.csrf_token,
            )
        status_events = [
            event for event in self.repo.security_events
            if event.event_type == "ACCOUNT_DISABLE"
        ]
        self.assertEqual(1, len(status_events))

    async def test_librarian_cannot_disable_privileged_or_self_account(self) -> None:
        account = await self.provision_and_activate("LIB-PRIVILEGED-0001")
        await self.service.role_action(
            target_user_id=account.user_id, role=RoleCode.LIBRARIAN,
            action=RoleAction.GRANT, actor=self.admin,
            reason_code="APPROVED_STAFF_ROLE", idempotency_key="role-grant-privileged",
        )
        with self.assertRaisesRegex(IdentityError, "TARGET_ROLE_FORBIDDEN"):
            await self.service.status_action(
                target_user_id=account.user_id, action=AccountStatusAction.DISABLE,
                actor=self.librarian, reason_code="NOT_AUTHORIZED",
                idempotency_key="status-forbidden-0001",
            )
        self_actor = AuthenticatedPrincipal(
            user_id=account.user_id, roles=frozenset({"research_admin"}),
        )
        with self.assertRaisesRegex(IdentityError, "SELF_STATUS_CHANGE_FORBIDDEN"):
            await self.service.status_action(
                target_user_id=account.user_id, action=AccountStatusAction.DISABLE,
                actor=self_actor, reason_code="SELF_ACTION",
                idempotency_key="status-self-0001",
            )

    async def test_personalization_consent_is_explicit_versioned_and_reversible(self) -> None:
        await self.provision_and_activate("LIB-CONSENT-0001")
        login = await self.service.login(
            identifier_type=IdentifierType.READER_NUMBER,
            identifier="LIB-CONSENT-0001", password="Correct-Horse-2026",
        )
        actor = AuthenticatedPrincipal(
            user_id=login.account.user_id, roles=frozenset({"user"}),
            token_id=str(uuid4()), session_id=login.session_uuid,
            auth_version=login.account.auth_version,
            role_version=login.account.role_version,
        )
        scope = ConsentScope.PERSONALIZED_RECOMMENDATION
        granted = await self.service.consent_action(
            scope=scope, action=ConsentAction.GRANT, policy_version="privacy-v1",
            source="LOGIN_ONBOARDING",
            evidence_hash=consent_evidence_hash(
                policy_version="privacy-v1", scope=scope, action=ConsentAction.GRANT,
            ),
            actor=actor,
        )
        withdrawn = await self.service.consent_action(
            scope=scope, action=ConsentAction.WITHDRAW, policy_version="privacy-v1",
            source="SETTINGS",
            evidence_hash=consent_evidence_hash(
                policy_version="privacy-v1", scope=scope, action=ConsentAction.WITHDRAW,
            ),
            actor=actor,
        )
        self.assertTrue(granted[scope])
        self.assertFalse(withdrawn[scope])
        self.assertEqual([1, 2], [fact.consent_version for fact in self.repo.consents])

    async def test_guest_has_no_identity_write_path(self) -> None:
        self.assertFalse(hasattr(self.service, "create_guest"))
        self.assertEqual(0, len(self.repo.accounts))
        self.assertEqual(0, len(self.repo.sessions))
        self.assertEqual(0, len(self.repo.security_events))


if __name__ == "__main__":
    unittest.main()
