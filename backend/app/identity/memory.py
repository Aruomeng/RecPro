"""Deterministic in-memory IAM repository used before any database approval."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import hashlib
from uuid import UUID, uuid4

from backend.app.identity.domain import (
    AccountKind,
    AccountProvisioningResult,
    AccountStatus,
    AccountStatusAction,
    ActionTokenPurpose,
    ActionTokenRecord,
    AuthSession,
    ConsentAction,
    ConsentFact,
    ConsentScope,
    IdentifierType,
    IdentityError,
    LoginIdentifier,
    PasswordCredential,
    RefreshTokenRecord,
    RoleAction,
    RoleCode,
    SecurityEvent,
    UserAccount,
    UserRoleFact,
)


class InMemoryIdentityRepository:
    def __init__(self, *, first_user_id: int = 10_000) -> None:
        self._next_user_id = first_user_id
        self._next_identifier_id = 1
        self._lock = asyncio.Lock()
        self.accounts: dict[int, UserAccount] = {}
        self.identifiers: dict[tuple[IdentifierType, bytes], LoginIdentifier] = {}
        self.credentials: dict[int, PasswordCredential] = {}
        self.role_facts: list[UserRoleFact] = []
        self.sessions: dict[UUID, AuthSession] = {}
        self.refresh_tokens: dict[bytes, RefreshTokenRecord] = {}
        self.action_tokens: dict[tuple[ActionTokenPurpose, bytes], ActionTokenRecord] = {}
        self.consents: list[ConsentFact] = []
        self.security_events: list[SecurityEvent] = []
        self.idempotency: dict[str, AccountProvisioningResult] = {}

    async def provision_reader(
        self, *, display_name: str, identifier_type: IdentifierType,
        identifier_hash: bytes, display_suffix: str, actor_user_id: int,
        activation: ActionTokenRecord, idempotency_key: str,
    ) -> AccountProvisioningResult:
        async with self._lock:
            if idempotency_key in self.idempotency:
                prior = self.idempotency[idempotency_key]
                return AccountProvisioningResult(
                    account=deepcopy(prior.account), activation_code=None, replayed=True,
                )
            key = (identifier_type, identifier_hash)
            if key in self.identifiers:
                raise IdentityError("IDENTIFIER_ALREADY_EXISTS")
            now = activation.created_at
            user_id = self._next_user_id
            self._next_user_id += 1
            account = UserAccount(
                user_id=user_id, account_uuid=uuid4(), display_name=display_name,
                account_kind=AccountKind.HUMAN, status=AccountStatus.PENDING_ACTIVATION,
                auth_version=1, role_version=1, must_change_password=True,
                failed_login_count=0, locked_until=None, last_login_at=None,
                disabled_reason=None, created_by_user_id=actor_user_id,
                created_at=now, updated_at=now,
            )
            identifier = LoginIdentifier(
                identifier_id=self._next_identifier_id, user_id=user_id,
                identifier_type=identifier_type, identifier_hash=identifier_hash,
                display_suffix=display_suffix, normalization_version="reader-id-nfkc-upper-v1",
                status="ACTIVE", created_at=now,
            )
            self._next_identifier_id += 1
            activation.user_id = user_id
            self.accounts[user_id] = account
            self.identifiers[key] = identifier
            self.action_tokens[(activation.purpose, activation.token_hash)] = activation
            self.role_facts.append(UserRoleFact(
                fact_uuid=uuid4(), user_id=user_id, role=RoleCode.USER,
                role_version=1, action=RoleAction.GRANT, actor_user_id=actor_user_id,
                reason_code="READER_ACCOUNT_PROVISIONED", idempotency_key=f"{idempotency_key}:role:user",
                occurred_at=now,
            ))
            result = AccountProvisioningResult(account=deepcopy(account), activation_code=None)
            self.idempotency[idempotency_key] = result
            return deepcopy(result)

    async def find_identifier(self, identifier_type: IdentifierType, identifier_hash: bytes) -> LoginIdentifier | None:
        return deepcopy(self.identifiers.get((identifier_type, identifier_hash)))

    async def get_account(self, user_id: int) -> UserAccount | None:
        return deepcopy(self.accounts.get(user_id))

    async def get_credential(self, user_id: int) -> PasswordCredential | None:
        return deepcopy(self.credentials.get(user_id))

    async def set_password_and_activate(self, *, user_id: int, credential: PasswordCredential, token_hash: bytes, now: datetime) -> UserAccount:
        async with self._lock:
            account = self._require_account(user_id)
            token = self.action_tokens.get((ActionTokenPurpose.ACTIVATE_ACCOUNT, token_hash))
            timestamp = _time(now)
            if token is None or token.user_id != user_id or token.consumed_at or token.revoked_at or token.expires_at <= timestamp:
                raise IdentityError("ACTION_TOKEN_INVALID")
            if account.status is not AccountStatus.PENDING_ACTIVATION:
                raise IdentityError("ACCOUNT_NOT_PENDING")
            token.consumed_at = timestamp
            self.credentials[user_id] = deepcopy(credential)
            account.status = AccountStatus.ACTIVE
            account.must_change_password = False
            account.auth_version += 1
            account.updated_at = timestamp
            return deepcopy(account)

    async def update_login_failure(self, user_id: int, *, now: datetime, lock_seconds: int, threshold: int) -> None:
        async with self._lock:
            account = self._require_account(user_id)
            account.failed_login_count += 1
            timestamp = _time(now)
            if account.failed_login_count >= threshold:
                account.locked_until = timestamp + timedelta(seconds=lock_seconds)
                account.failed_login_count = 0
            account.updated_at = timestamp

    async def complete_login(self, user_id: int, *, now: datetime) -> UserAccount:
        async with self._lock:
            account = self._require_account(user_id)
            timestamp = _time(now)
            account.failed_login_count = 0
            account.locked_until = None
            account.last_login_at = timestamp
            account.updated_at = timestamp
            return deepcopy(account)

    async def effective_roles(self, user_id: int) -> frozenset[RoleCode]:
        latest: dict[RoleCode, UserRoleFact] = {}
        for fact in self.role_facts:
            if fact.user_id == user_id and (
                fact.role not in latest or fact.role_version > latest[fact.role].role_version
            ):
                latest[fact.role] = fact
        return frozenset(role for role, fact in latest.items() if fact.action is RoleAction.GRANT)

    async def create_session(self, session: AuthSession, refresh: RefreshTokenRecord) -> None:
        async with self._lock:
            if session.session_uuid in self.sessions or refresh.token_hash in self.refresh_tokens:
                raise IdentityError("SESSION_ALREADY_EXISTS")
            self.sessions[session.session_uuid] = deepcopy(session)
            self.refresh_tokens[refresh.token_hash] = deepcopy(refresh)

    async def find_refresh(self, token_hash: bytes) -> RefreshTokenRecord | None:
        return deepcopy(self.refresh_tokens.get(token_hash))

    async def get_session(self, session_uuid: UUID) -> AuthSession | None:
        return deepcopy(self.sessions.get(session_uuid))

    async def rotate_refresh(self, *, consumed_uuid: UUID, replacement: RefreshTokenRecord, now: datetime) -> None:
        async with self._lock:
            timestamp = _time(now)
            current = next((item for item in self.refresh_tokens.values() if item.token_uuid == consumed_uuid), None)
            if current is None or current.consumed_at or current.revoked_at:
                raise IdentityError("REFRESH_TOKEN_REUSED")
            current.consumed_at = timestamp
            self.refresh_tokens[replacement.token_hash] = deepcopy(replacement)
            self.sessions[replacement.session_uuid].last_seen_at = timestamp

    async def revoke_session(self, session_uuid: UUID, *, reason: str, now: datetime) -> None:
        async with self._lock:
            session = self.sessions.get(session_uuid)
            if session is None:
                return
            timestamp = _time(now)
            session.revoked_at = session.revoked_at or timestamp
            session.revoke_reason = session.revoke_reason or reason
            for token in self.refresh_tokens.values():
                if token.session_uuid == session_uuid:
                    token.revoked_at = token.revoked_at or timestamp

    async def revoke_user_sessions(self, user_id: int, *, reason: str, now: datetime) -> None:
        for session in list(self.sessions.values()):
            if session.user_id == user_id:
                await self.revoke_session(session.session_uuid, reason=reason, now=now)

    async def find_action_token(self, token_hash: bytes, purpose: ActionTokenPurpose) -> ActionTokenRecord | None:
        return deepcopy(self.action_tokens.get((purpose, token_hash)))

    async def append_action_token(self, token: ActionTokenRecord) -> None:
        async with self._lock:
            self.action_tokens[(token.purpose, token.token_hash)] = deepcopy(token)

    async def replace_password(self, *, user_id: int, credential: PasswordCredential, token_hash: bytes | None, now: datetime) -> UserAccount:
        async with self._lock:
            account = self._require_account(user_id)
            timestamp = _time(now)
            if token_hash is not None:
                token = self.action_tokens.get((ActionTokenPurpose.RESET_PASSWORD, token_hash))
                if token is None or token.user_id != user_id or token.consumed_at or token.revoked_at or token.expires_at <= timestamp:
                    raise IdentityError("ACTION_TOKEN_INVALID")
                token.consumed_at = timestamp
            self.credentials[user_id] = deepcopy(credential)
            account.auth_version += 1
            account.must_change_password = False
            account.updated_at = timestamp
            return deepcopy(account)

    async def append_role_fact(self, fact: UserRoleFact) -> tuple[UserAccount, bool]:
        async with self._lock:
            account = self._require_account(fact.user_id)
            if any(item.idempotency_key == fact.idempotency_key for item in self.role_facts):
                return deepcopy(account), True
            account.role_version += 1
            self.role_facts.append(UserRoleFact(
                fact_uuid=fact.fact_uuid, user_id=fact.user_id, role=fact.role,
                role_version=account.role_version, action=fact.action,
                actor_user_id=fact.actor_user_id, reason_code=fact.reason_code,
                idempotency_key=fact.idempotency_key, occurred_at=fact.occurred_at,
            ))
            account.updated_at = fact.occurred_at
            return deepcopy(account), False

    async def set_account_status(
        self, *, user_id: int, action: AccountStatusAction, reason_code: str,
        idempotency_key: str, event_uuid: UUID, actor_user_id: int, now: datetime,
    ) -> tuple[UserAccount, bool]:
        async with self._lock:
            account = self._require_account(user_id)
            prior = next(
                (event for event in self.security_events if event.event_uuid == event_uuid), None,
            )
            if prior is not None:
                if prior.user_id != user_id or prior.actor_user_id != actor_user_id:
                    raise IdentityError("IDEMPOTENCY_KEY_CONFLICT")
                return deepcopy(account), True
            target_status = (
                AccountStatus.ACTIVE
                if action is AccountStatusAction.ENABLE
                else AccountStatus.DISABLED
            )
            if action is AccountStatusAction.ENABLE and account.status is AccountStatus.PENDING_ACTIVATION:
                raise IdentityError("ACCOUNT_NOT_ACTIVATED")
            account.status = target_status
            account.disabled_reason = None if target_status is AccountStatus.ACTIVE else reason_code[:64]
            account.auth_version += 1
            account.updated_at = now
            self.security_events.append(SecurityEvent(
                event_uuid=event_uuid, event_type=f"ACCOUNT_{action.value}",
                outcome="SUCCESS", user_id=user_id, actor_user_id=actor_user_id,
                session_uuid=None, identifier_hash=None, request_id=event_uuid,
                reason_code=reason_code[:64], occurred_at=now,
                metadata={"idempotency_key_hash": _idempotency_hash(idempotency_key)},
            ))
            return deepcopy(account), False

    async def append_consent(self, fact: ConsentFact) -> None:
        async with self._lock:
            if any(item.consent_uuid == fact.consent_uuid for item in self.consents):
                return
            latest = max((item.consent_version for item in self.consents if item.user_id == fact.user_id and item.scope is fact.scope), default=0)
            if fact.consent_version != latest + 1:
                raise IdentityError("CONSENT_VERSION_CONFLICT")
            self.consents.append(fact)

    async def next_consent_version(self, user_id: int, scope: ConsentScope) -> int:
        return max(
            (item.consent_version for item in self.consents if item.user_id == user_id and item.scope is scope),
            default=0,
        ) + 1

    async def effective_consents(self, user_id: int) -> dict[ConsentScope, bool]:
        result = {scope: False for scope in ConsentScope}
        latest: dict[ConsentScope, ConsentFact] = {}
        for fact in self.consents:
            if fact.user_id == user_id and (
                fact.scope not in latest or fact.consent_version > latest[fact.scope].consent_version
            ):
                latest[fact.scope] = fact
        for scope, fact in latest.items():
            result[scope] = fact.action is ConsentAction.GRANT
        return result

    async def append_security_event(self, event: SecurityEvent) -> None:
        if len(str(event.metadata)) > 2048:
            raise IdentityError("SECURITY_METADATA_TOO_LARGE")
        if any(item.event_uuid == event.event_uuid for item in self.security_events):
            return
        self.security_events.append(event)

    def _require_account(self, user_id: int) -> UserAccount:
        account = self.accounts.get(user_id)
        if account is None:
            raise IdentityError("ACCOUNT_NOT_FOUND")
        return account


def _time(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("repository time must be datetime")
    return value.astimezone(UTC)


def _idempotency_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


__all__ = ["InMemoryIdentityRepository"]
