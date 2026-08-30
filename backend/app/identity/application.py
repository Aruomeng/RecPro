"""Identity use cases with explicit security state transitions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import hmac
from typing import Callable
from uuid import UUID, uuid4, uuid5

from backend.app.identity.domain import (
    AccountProvisioningResult,
    AccountStatus,
    AccountStatusAction,
    ActionTokenPurpose,
    ActionTokenRecord,
    AuthSession,
    ConsentAction,
    ConsentFact,
    ConsentScope,
    DeclaredProfile,
    IdentifierType,
    IdentityError,
    LoginResult,
    PasswordCredential,
    RefreshTokenRecord,
    RoleAction,
    RoleCode,
    ROLE_PERMISSIONS,
    SecurityEvent,
    UserAccount,
    UserRoleFact,
)
from backend.app.identity.ports import (
    AccessTokenIssuer,
    IdentifierService,
    IdentityRepository,
    PasswordService,
    SecretTokenService,
)
from backend.app.shared_kernel.contracts.auth import AuthenticatedPrincipal


class IdentityService:
    """Coordinates local login without exposing raw credential material."""

    def __init__(
        self, *, repository: IdentityRepository, passwords: PasswordService,
        identifiers: IdentifierService, secrets: SecretTokenService,
        access_tokens: AccessTokenIssuer,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        refresh_ttl_seconds: int = 8 * 60 * 60,
        lock_threshold: int = 5, lock_seconds: int = 15 * 60,
    ) -> None:
        if not 3600 <= refresh_ttl_seconds <= 7 * 24 * 3600:
            raise ValueError("refresh lifetime is outside the bounded local policy")
        self._repo = repository
        self._passwords = passwords
        self._identifiers = identifiers
        self._secrets = secrets
        self._access_tokens = access_tokens
        self._clock = clock
        self._refresh_ttl = refresh_ttl_seconds
        self._lock_threshold = lock_threshold
        self._lock_seconds = lock_seconds

    async def provision_reader(
        self, *, display_name: str, identifier_type: IdentifierType,
        identifier: str, actor: AuthenticatedPrincipal, idempotency_key: str,
    ) -> AccountProvisioningResult:
        _require_any_role(actor, RoleCode.LIBRARIAN, RoleCode.RESEARCH_ADMIN)
        clean_name = display_name.strip()
        if not 1 <= len(clean_name) <= 80 or not 8 <= len(idempotency_key) <= 128:
            raise IdentityError("INVALID_ACCOUNT_INPUT")
        normalized = self._identifiers.normalize(identifier_type, identifier)
        digest = self._identifiers.digest(normalized)
        raw_code = self._secrets.generate()
        now = self._now()
        action = ActionTokenRecord(
            token_uuid=uuid4(), user_id=0, purpose=ActionTokenPurpose.ACTIVATE_ACCOUNT,
            token_hash=self._secrets.digest(raw_code), issued_by_user_id=actor.user_id,
            expires_at=now + timedelta(hours=24), created_at=now,
        )
        result = await self._repo.provision_reader(
            display_name=clean_name, identifier_type=identifier_type,
            identifier_hash=digest, display_suffix=normalized[-8:],
            actor_user_id=actor.user_id, activation=action,
            idempotency_key=idempotency_key,
        )
        await self._event(
            event_type="ACCOUNT_PROVISIONED", outcome="SUCCESS",
            user_id=result.account.user_id, actor_user_id=actor.user_id,
            reason_code="IDEMPOTENT_REPLAY" if result.replayed else "LIBRARIAN_CREATED",
            identifier_hash=digest,
        )
        return AccountProvisioningResult(
            account=result.account,
            activation_code=None if result.replayed else raw_code,
            replayed=result.replayed,
        )

    async def activate(
        self, *, identifier_type: IdentifierType, identifier: str,
        activation_code: str, new_password: str,
    ) -> UserAccount:
        normalized = self._identifiers.normalize(identifier_type, identifier)
        identifier_hash = self._identifiers.digest(normalized)
        login_identifier = await self._repo.find_identifier(identifier_type, identifier_hash)
        if login_identifier is None or login_identifier.status != "ACTIVE":
            self._passwords.burn_unknown(new_password)
            raise IdentityError("ACTION_TOKEN_INVALID")
        now = self._now()
        credential = PasswordCredential(
            user_id=login_identifier.user_id,
            password_hash=self._passwords.hash(new_password), algorithm="ARGON2ID",
            parameters_version="argon2id-v1", password_version=1,
            changed_at=now, expires_at=None, updated_at=now,
        )
        account = await self._repo.set_password_and_activate(
            user_id=login_identifier.user_id, credential=credential,
            token_hash=self._secrets.digest(activation_code), now=now,
        )
        await self._event(
            event_type="ACCOUNT_ACTIVATED", outcome="SUCCESS", user_id=account.user_id,
            actor_user_id=account.user_id, reason_code="ONE_TIME_CODE_CONSUMED",
            identifier_hash=identifier_hash,
        )
        return account

    async def login(
        self, *, identifier_type: IdentifierType, identifier: str, password: str,
        device_type: str = "KIOSK",
    ) -> LoginResult:
        normalized = self._identifiers.normalize(identifier_type, identifier)
        identifier_hash = self._identifiers.digest(normalized)
        login_identifier = await self._repo.find_identifier(identifier_type, identifier_hash)
        if login_identifier is None or login_identifier.status != "ACTIVE":
            self._passwords.burn_unknown(password)
            await self._event(
                event_type="LOGIN", outcome="DENIED", user_id=None,
                actor_user_id=None, reason_code="INVALID_CREDENTIALS",
                identifier_hash=identifier_hash,
            )
            raise IdentityError("INVALID_CREDENTIALS")
        account = await self._repo.get_account(login_identifier.user_id)
        credential = await self._repo.get_credential(login_identifier.user_id)
        now = self._now()
        if (
            account is None or credential is None or account.status is not AccountStatus.ACTIVE
            or (account.locked_until is not None and account.locked_until > now)
        ):
            self._passwords.burn_unknown(password)
            await self._event(
                event_type="LOGIN", outcome="DENIED",
                user_id=account.user_id if account is not None else None,
                actor_user_id=None, reason_code="INVALID_CREDENTIALS",
                identifier_hash=identifier_hash,
            )
            raise IdentityError("INVALID_CREDENTIALS")
        if not self._passwords.verify(credential.password_hash, password):
            await self._repo.update_login_failure(
                account.user_id, now=now, lock_seconds=self._lock_seconds,
                threshold=self._lock_threshold,
            )
            await self._event(
                event_type="LOGIN", outcome="DENIED", user_id=account.user_id,
                actor_user_id=None, reason_code="INVALID_CREDENTIALS",
                identifier_hash=identifier_hash,
            )
            raise IdentityError("INVALID_CREDENTIALS")
        roles = await self._repo.effective_roles(account.user_id)
        if not roles or RoleCode.SERVICE_WORKER in roles:
            raise IdentityError("INTERACTIVE_LOGIN_FORBIDDEN")
        account = await self._repo.complete_login(account.user_id, now=now)
        result = await self._new_session(account, roles, device_type=device_type)
        await self._event(
            event_type="LOGIN", outcome="SUCCESS", user_id=account.user_id,
            actor_user_id=account.user_id, reason_code="PASSWORD_VERIFIED",
            session_uuid=result.session_uuid, identifier_hash=identifier_hash,
        )
        return result

    async def refresh(self, *, refresh_token: str, csrf_token: str) -> LoginResult:
        now = self._now()
        token_hash = self._secrets.digest(refresh_token)
        record = await self._repo.find_refresh(token_hash)
        if record is None:
            raise IdentityError("REFRESH_TOKEN_INVALID")
        session = await self._repo.get_session(record.session_uuid)
        if session is None:
            raise IdentityError("REFRESH_TOKEN_INVALID")
        if record.consumed_at is not None:
            await self._repo.revoke_session(session.session_uuid, reason="TOKEN_REUSE", now=now)
            raise IdentityError("REFRESH_TOKEN_REUSED")
        if (
            record.revoked_at is not None or record.expires_at <= now
            or session.revoked_at is not None or session.absolute_expires_at <= now
            or not hmac.compare_digest(session.csrf_secret_hash, self._secrets.digest(csrf_token))
        ):
            raise IdentityError("REFRESH_TOKEN_INVALID")
        account = await self._repo.get_account(session.user_id)
        if (
            account is None or account.status is not AccountStatus.ACTIVE
            or account.auth_version != session.auth_version_at_issue
            or account.role_version != session.role_version_at_issue
        ):
            await self._repo.revoke_session(session.session_uuid, reason="ACCOUNT_VERSION_CHANGED", now=now)
            raise IdentityError("REFRESH_TOKEN_INVALID")
        raw_refresh = self._secrets.generate()
        replacement = RefreshTokenRecord(
            token_uuid=uuid4(), session_uuid=session.session_uuid,
            token_hash=self._secrets.digest(raw_refresh), parent_token_uuid=record.token_uuid,
            issued_at=now, expires_at=session.absolute_expires_at,
        )
        try:
            await self._repo.rotate_refresh(
                consumed_uuid=record.token_uuid, replacement=replacement, now=now,
            )
        except IdentityError as exc:
            if exc.code == "REFRESH_TOKEN_REUSED":
                await self._repo.revoke_session(
                    session.session_uuid, reason="TOKEN_REUSE", now=now,
                )
            raise
        roles = await self._repo.effective_roles(account.user_id)
        access_token, expires_in = self._access_tokens.issue(
            account=account, roles=roles, session_id=session.session_uuid,
        )
        return LoginResult(
            access_token=access_token, expires_in=expires_in,
            refresh_token=raw_refresh, csrf_token=csrf_token,
            session_uuid=session.session_uuid, account=account, roles=roles,
            consents=await self._repo.effective_consents(account.user_id),
        )

    async def logout(self, actor: AuthenticatedPrincipal) -> None:
        if actor.session_id is None:
            raise IdentityError("SESSION_REQUIRED")
        now = self._now()
        await self._repo.revoke_session(actor.session_id, reason="LOGOUT", now=now)
        await self._event(
            event_type="LOGOUT", outcome="SUCCESS", user_id=actor.user_id,
            actor_user_id=actor.user_id, reason_code="USER_REQUESTED",
            session_uuid=actor.session_id,
        )

    async def issue_password_reset_code(
        self, *, target_user_id: int, actor: AuthenticatedPrincipal,
    ) -> str:
        _require_any_role(actor, RoleCode.LIBRARIAN, RoleCode.RESEARCH_ADMIN)
        account = await self._repo.get_account(target_user_id)
        if account is None or account.account_kind.value != "HUMAN":
            raise IdentityError("ACCOUNT_NOT_FOUND")
        await self._require_manageable_reader_target(actor, target_user_id)
        raw_code = self._secrets.generate()
        now = self._now()
        await self._repo.append_action_token(ActionTokenRecord(
            token_uuid=uuid4(), user_id=target_user_id,
            purpose=ActionTokenPurpose.RESET_PASSWORD,
            token_hash=self._secrets.digest(raw_code), issued_by_user_id=actor.user_id,
            expires_at=now + timedelta(minutes=15), created_at=now,
        ))
        await self._event(
            event_type="PASSWORD_RESET_CODE_ISSUED", outcome="SUCCESS",
            user_id=target_user_id, actor_user_id=actor.user_id,
            reason_code="LIBRARIAN_REQUESTED",
        )
        return raw_code

    async def issue_activation_code(
        self, *, target_user_id: int, actor: AuthenticatedPrincipal,
    ) -> str:
        _require_any_role(actor, RoleCode.LIBRARIAN, RoleCode.RESEARCH_ADMIN)
        account = await self._repo.get_account(target_user_id)
        if account is None or account.account_kind.value != "HUMAN":
            raise IdentityError("ACCOUNT_NOT_FOUND")
        if account.status is not AccountStatus.PENDING_ACTIVATION:
            raise IdentityError("ACCOUNT_NOT_PENDING")
        await self._require_manageable_reader_target(actor, target_user_id)
        raw_code = self._secrets.generate()
        now = self._now()
        await self._repo.append_action_token(ActionTokenRecord(
            token_uuid=uuid4(), user_id=target_user_id,
            purpose=ActionTokenPurpose.ACTIVATE_ACCOUNT,
            token_hash=self._secrets.digest(raw_code), issued_by_user_id=actor.user_id,
            expires_at=now + timedelta(hours=24), created_at=now,
        ))
        await self._event(
            event_type="ACTIVATION_CODE_ISSUED", outcome="SUCCESS",
            user_id=target_user_id, actor_user_id=actor.user_id,
            reason_code="LIBRARIAN_REQUESTED",
        )
        return raw_code

    async def reset_password(
        self, *, identifier_type: IdentifierType, identifier: str,
        reset_code: str, new_password: str,
    ) -> UserAccount:
        normalized = self._identifiers.normalize(identifier_type, identifier)
        login_identifier = await self._repo.find_identifier(
            identifier_type, self._identifiers.digest(normalized),
        )
        if login_identifier is None or login_identifier.status != "ACTIVE":
            self._passwords.burn_unknown(new_password)
            raise IdentityError("ACTION_TOKEN_INVALID")
        existing = await self._repo.get_credential(login_identifier.user_id)
        now = self._now()
        credential = PasswordCredential(
            user_id=login_identifier.user_id,
            password_hash=self._passwords.hash(new_password), algorithm="ARGON2ID",
            parameters_version="argon2id-v1",
            password_version=(existing.password_version if existing else 0) + 1,
            changed_at=now, expires_at=None, updated_at=now,
        )
        account = await self._repo.replace_password(
            user_id=login_identifier.user_id, credential=credential,
            token_hash=self._secrets.digest(reset_code), now=now,
        )
        await self._repo.revoke_user_sessions(account.user_id, reason="PASSWORD_CHANGED", now=now)
        await self._event(
            event_type="PASSWORD_RESET", outcome="SUCCESS", user_id=account.user_id,
            actor_user_id=account.user_id, reason_code="ONE_TIME_CODE_CONSUMED",
        )
        return account

    async def change_password(
        self, *, actor: AuthenticatedPrincipal, current_password: str, new_password: str,
    ) -> UserAccount:
        credential = await self._repo.get_credential(actor.user_id)
        if credential is None or not self._passwords.verify(credential.password_hash, current_password):
            raise IdentityError("INVALID_CREDENTIALS")
        now = self._now()
        replacement = PasswordCredential(
            user_id=actor.user_id, password_hash=self._passwords.hash(new_password),
            algorithm="ARGON2ID", parameters_version="argon2id-v1",
            password_version=credential.password_version + 1,
            changed_at=now, expires_at=None, updated_at=now,
        )
        account = await self._repo.replace_password(
            user_id=actor.user_id, credential=replacement, token_hash=None, now=now,
        )
        await self._repo.revoke_user_sessions(actor.user_id, reason="PASSWORD_CHANGED", now=now)
        return account

    async def role_action(
        self, *, target_user_id: int, role: RoleCode, action: RoleAction,
        actor: AuthenticatedPrincipal, reason_code: str, idempotency_key: str,
    ) -> UserAccount:
        _require_any_role(actor, RoleCode.RESEARCH_ADMIN)
        if role is RoleCode.SERVICE_WORKER:
            raise IdentityError("SERVICE_ROLE_BROWSER_ASSIGNMENT_FORBIDDEN")
        account = await self._repo.get_account(target_user_id)
        if account is None:
            raise IdentityError("ACCOUNT_NOT_FOUND")
        now = self._now()
        updated, replayed = await self._repo.append_role_fact(UserRoleFact(
            fact_uuid=uuid4(), user_id=target_user_id, role=role,
            role_version=account.role_version + 1, action=action,
            actor_user_id=actor.user_id, reason_code=reason_code[:64],
            idempotency_key=idempotency_key, occurred_at=now,
        ))
        if not replayed:
            await self._repo.revoke_user_sessions(target_user_id, reason="ROLE_VERSION_CHANGED", now=now)
        return updated

    async def status_action(
        self, *, target_user_id: int, action: AccountStatusAction,
        actor: AuthenticatedPrincipal, reason_code: str, idempotency_key: str,
    ) -> UserAccount:
        _require_any_role(actor, RoleCode.LIBRARIAN, RoleCode.RESEARCH_ADMIN)
        if actor.user_id == target_user_id:
            raise IdentityError("SELF_STATUS_CHANGE_FORBIDDEN")
        account = await self._repo.get_account(target_user_id)
        if account is None or account.account_kind.value != "HUMAN":
            raise IdentityError("ACCOUNT_NOT_FOUND")
        roles = await self._repo.effective_roles(target_user_id)
        if actor.has_role(RoleCode.LIBRARIAN.value) and not actor.has_role(RoleCode.RESEARCH_ADMIN.value):
            if not roles or not roles.issubset({RoleCode.USER}):
                raise IdentityError("TARGET_ROLE_FORBIDDEN")
        if not 8 <= len(idempotency_key) <= 128 or not reason_code:
            raise IdentityError("INVALID_STATUS_ACTION")
        now = self._now()
        event_uuid = uuid5(
            UUID("208a9e72-9e7f-5adc-a8d7-f92f74dff87a"),
            f"status:{actor.user_id}:{target_user_id}:{idempotency_key}",
        )
        updated, replayed = await self._repo.set_account_status(
            user_id=target_user_id, action=action, reason_code=reason_code,
            idempotency_key=idempotency_key, event_uuid=event_uuid,
            actor_user_id=actor.user_id, now=now,
        )
        if not replayed:
            await self._repo.revoke_user_sessions(
                target_user_id, reason="ACCOUNT_STATUS_CHANGED", now=now,
            )
        return updated

    async def consent_action(
        self, *, scope: ConsentScope, action: ConsentAction,
        policy_version: str, source: str, evidence_hash: str,
        actor: AuthenticatedPrincipal,
    ) -> dict[ConsentScope, bool]:
        if actor.session_id is None or RoleCode.USER.value not in actor.roles:
            raise IdentityError("USER_SESSION_REQUIRED")
        version = await self._repo.next_consent_version(actor.user_id, scope)
        if len(policy_version) > 64 or len(evidence_hash) != 64:
            raise IdentityError("INVALID_CONSENT_INPUT")
        await self._repo.append_consent(ConsentFact(
            consent_uuid=uuid4(), user_id=actor.user_id, scope=scope,
            consent_version=version, action=action, policy_version=policy_version,
            source=source[:24], evidence_hash=evidence_hash,
            session_uuid=actor.session_id, occurred_at=self._now(),
        ))
        return await self._repo.effective_consents(actor.user_id)

    async def read_declared_profile(
        self, *, actor: AuthenticatedPrincipal,
    ) -> tuple[DeclaredProfile | None, bool]:
        """Read a declared profile only after the matching consent is present.

        The account and consent checks happen before the profile repository is
        queried.  This keeps an unconsented profile out of both SQL traces and
        recommendation context; the compatibility projection is not an
        authority for consent.
        """

        _require_profile_actor(actor, "profile.self.read")
        consents = await self._repo.effective_consents(actor.user_id)
        granted = bool(consents[ConsentScope.DECLARED_PROFILE])
        if not granted:
            return None, False
        return await self._repo.get_declared_profile(actor.user_id), True

    async def update_declared_profile(
        self, *, actor: AuthenticatedPrincipal, major: str | None,
        grade: str | None, research_direction: str | None,
        preferred_language: str | None,
    ) -> DeclaredProfile:
        """Append a new declared-profile version and refresh its projection."""

        _require_profile_actor(actor, "profile.self.update")
        consents = await self._repo.effective_consents(actor.user_id)
        if not consents[ConsentScope.DECLARED_PROFILE]:
            raise IdentityError("PERSONALIZATION_CONSENT_REQUIRED")
        values = {
            "major": _profile_text(major, 128),
            "grade": _profile_text(grade, 32),
            "research_direction": _profile_text(research_direction, 255),
            "preferred_language": _profile_text(preferred_language, 32),
        }
        return await self._repo.save_declared_profile(
            user_id=actor.user_id,
            major=values["major"],
            grade=values["grade"],
            research_direction=values["research_direction"],
            preferred_language=values["preferred_language"],
            personalization_enabled=True,
            now=self._now(),
        )

    async def validate_principal(
        self, principal: AuthenticatedPrincipal,
    ) -> AuthenticatedPrincipal:
        if (
            principal.session_id is None or principal.auth_version is None
            or principal.role_version is None
        ):
            raise IdentityError("SESSION_REQUIRED")
        now = self._now()
        account = await self._repo.get_account(principal.user_id)
        session = await self._repo.get_session(principal.session_id)
        roles = await self._repo.effective_roles(principal.user_id)
        if (
            account is None or account.status is not AccountStatus.ACTIVE
            or session is None or session.user_id != principal.user_id
            or session.revoked_at is not None or session.absolute_expires_at <= now
            or account.auth_version != principal.auth_version
            or account.role_version != principal.role_version
            or session.auth_version_at_issue != account.auth_version
            or session.role_version_at_issue != account.role_version
            or {role.value for role in roles} != set(principal.roles)
        ):
            raise IdentityError("AUTHENTICATION_INVALID")
        permissions = frozenset(
            permission for role in roles for permission in ROLE_PERMISSIONS[role]
        )
        consents = await self._repo.effective_consents(principal.user_id)
        dynamic_permissions: set[str] = set()
        if consents[ConsentScope.PERSONALIZED_RECOMMENDATION]:
            dynamic_permissions.add("personalization.profile.use")
        if consents[ConsentScope.BEHAVIOR_LEARNING]:
            dynamic_permissions.add("personalization.behavior.write")
        return AuthenticatedPrincipal(
            user_id=principal.user_id, roles=principal.roles,
            token_id=principal.token_id, session_id=principal.session_id,
            auth_version=principal.auth_version, role_version=principal.role_version,
            expires_at=principal.expires_at,
            permissions=permissions | frozenset(dynamic_permissions),
        )

    async def account_summary(
        self, *, target_user_id: int, actor: AuthenticatedPrincipal,
    ) -> tuple[UserAccount, frozenset[RoleCode], dict[ConsentScope, bool]]:
        if actor.user_id != target_user_id:
            _require_any_role(actor, RoleCode.LIBRARIAN, RoleCode.RESEARCH_ADMIN)
            await self._require_manageable_reader_target(actor, target_user_id)
        account = await self._repo.get_account(target_user_id)
        if account is None:
            raise IdentityError("ACCOUNT_NOT_FOUND")
        return (
            account,
            await self._repo.effective_roles(target_user_id),
            await self._repo.effective_consents(target_user_id),
        )

    async def _require_manageable_reader_target(
        self, actor: AuthenticatedPrincipal, target_user_id: int,
    ) -> None:
        if actor.has_role(RoleCode.RESEARCH_ADMIN.value):
            return
        roles = await self._repo.effective_roles(target_user_id)
        if not roles or not roles.issubset({RoleCode.USER}):
            raise IdentityError("TARGET_ROLE_FORBIDDEN")

    async def _new_session(
        self, account: UserAccount, roles: frozenset[RoleCode], *, device_type: str,
    ) -> LoginResult:
        if device_type not in {"KIOSK", "BROWSER"}:
            raise IdentityError("INVALID_DEVICE_TYPE")
        now = self._now()
        session_uuid = uuid4()
        family_uuid = uuid4()
        raw_refresh = self._secrets.generate()
        csrf = self._secrets.generate()
        expires = now + timedelta(seconds=self._refresh_ttl)
        session = AuthSession(
            session_uuid=session_uuid, token_family_uuid=family_uuid,
            user_id=account.user_id, device_type=device_type,
            auth_version_at_issue=account.auth_version,
            role_version_at_issue=account.role_version,
            csrf_secret_hash=self._secrets.digest(csrf), issued_at=now,
            absolute_expires_at=expires, last_seen_at=now,
        )
        refresh = RefreshTokenRecord(
            token_uuid=uuid4(), session_uuid=session_uuid,
            token_hash=self._secrets.digest(raw_refresh), parent_token_uuid=None,
            issued_at=now, expires_at=expires,
        )
        await self._repo.create_session(session, refresh)
        access, ttl = self._access_tokens.issue(
            account=account, roles=roles, session_id=session_uuid,
        )
        return LoginResult(
            access_token=access, expires_in=ttl, refresh_token=raw_refresh,
            csrf_token=csrf, session_uuid=session_uuid, account=account,
            roles=roles, consents=await self._repo.effective_consents(account.user_id),
        )

    async def _event(
        self, *, event_type: str, outcome: str, user_id: int | None,
        actor_user_id: int | None, reason_code: str,
        session_uuid: UUID | None = None, identifier_hash: bytes | None = None,
    ) -> None:
        await self._repo.append_security_event(SecurityEvent(
            event_uuid=uuid4(), event_type=event_type, outcome=outcome,
            user_id=user_id, actor_user_id=actor_user_id,
            session_uuid=session_uuid, identifier_hash=identifier_hash,
            request_id=None, reason_code=reason_code, occurred_at=self._now(),
        ))

    def _now(self) -> datetime:
        return self._clock().astimezone(UTC)


def _require_any_role(actor: AuthenticatedPrincipal, *roles: RoleCode) -> None:
    if not any(actor.has_role(role.value) for role in roles):
        raise IdentityError("ROLE_REQUIRED")


def _require_profile_actor(actor: AuthenticatedPrincipal, permission: str) -> None:
    if actor.session_id is None or not actor.has_role(RoleCode.USER.value):
        raise IdentityError("USER_SESSION_REQUIRED")
    if not actor.has_permission(permission):
        raise IdentityError("ROLE_REQUIRED")


def _profile_text(value: str | None, max_length: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise IdentityError("INVALID_PROFILE_INPUT")
    clean = value.strip()
    if not clean:
        return None
    if len(clean) > max_length:
        raise IdentityError("INVALID_PROFILE_INPUT")
    return clean


def consent_evidence_hash(*, policy_version: str, scope: ConsentScope, action: ConsentAction) -> str:
    return hashlib.sha256(f"{policy_version}:{scope.value}:{action.value}".encode()).hexdigest()


__all__ = ["IdentityService", "consent_evidence_hash"]
