"""MySQL IAM repository with explicit, bounded security-state mutations.

Every write is an INSERT or an allowlisted UPDATE of current credential/session/
account security state. No method contains a physical delete, replacement, or
cascading operation.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
import hashlib
import json
from typing import Any
from uuid import UUID, uuid5

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
    DeclaredProfile,
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


ConnectionFactory = Callable[[], Awaitable[Any]]
_ACCOUNT_NAMESPACE = UUID("675649e8-62c7-55dd-b396-1183041624c4")
_ROLE_NAMESPACE = UUID("ab881af5-9654-59f1-b4f8-f9633b3169c6")
_ROLE_IDS = {
    RoleCode.USER: 1,
    RoleCode.LIBRARIAN: 2,
    RoleCode.RESEARCH_ADMIN: 3,
    RoleCode.SERVICE_WORKER: 4,
}
_ACCOUNT_COLUMNS = (
    "user_id, account_uuid, display_name, account_kind, status, auth_version, "
    "role_version, must_change_password, failed_login_count, locked_until, "
    "last_login_at, disabled_reason, created_by_user_id, created_at, updated_at"
)


class MySQLIdentityRepository:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory

    async def provision_reader(
        self, *, display_name: str, identifier_type: IdentifierType,
        identifier_hash: bytes, display_suffix: str, actor_user_id: int,
        activation: ActionTokenRecord, idempotency_key: str,
    ) -> AccountProvisioningResult:
        account_uuid = uuid5(
            _ACCOUNT_NAMESPACE, f"reader:{actor_user_id}:{idempotency_key}",
        )
        connection = await self._connection_factory()
        try:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    f"SELECT {_ACCOUNT_COLUMNS} FROM iam_user_account WHERE account_uuid = %s",
                    (str(account_uuid),),
                )
                prior = await cursor.fetchone()
                if prior is not None:
                    account = _account(prior)
                    await cursor.execute(
                        "SELECT user_id FROM iam_login_identifier WHERE identifier_hash = %s",
                        (identifier_hash,),
                    )
                    linked = await cursor.fetchone()
                    if linked is None or int(linked[0]) != account.user_id:
                        raise IdentityError("IDEMPOTENCY_KEY_CONFLICT")
                    await connection.rollback()
                    return AccountProvisioningResult(account=account, activation_code=None, replayed=True)
                now = _db_time(activation.created_at)
                await cursor.execute(
                    "INSERT INTO iam_user_account "
                    "(account_uuid, display_name, account_kind, status, auth_version, role_version, "
                    "must_change_password, failed_login_count, created_by_user_id, created_at, updated_at) "
                    "VALUES (%s, %s, 'HUMAN', 'PENDING_ACTIVATION', 1, 1, TRUE, 0, %s, %s, %s)",
                    (str(account_uuid), display_name, actor_user_id, now, now),
                )
                user_id = int(cursor.lastrowid)
                if user_id < 10_000:
                    raise IdentityError("REAL_USER_ID_BOUNDARY_VIOLATION")
                await cursor.execute(
                    "INSERT INTO iam_login_identifier "
                    "(user_id, identifier_type, identifier_hash, display_suffix, normalization_version, "
                    "status, created_at) VALUES (%s, %s, %s, %s, %s, 'ACTIVE', %s)",
                    (user_id, identifier_type.value, identifier_hash, display_suffix,
                     "reader-id-nfkc-upper-v1", now),
                )
                activation.user_id = user_id
                await cursor.execute(
                    "INSERT INTO iam_action_token "
                    "(token_uuid, user_id, purpose, token_hash, issued_by_user_id, expires_at, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (str(activation.token_uuid), user_id, activation.purpose.value,
                     activation.token_hash, activation.issued_by_user_id,
                     _db_time(activation.expires_at), now),
                )
                role_fact_uuid = uuid5(_ROLE_NAMESPACE, f"{account_uuid}:user:1")
                await cursor.execute(
                    "INSERT INTO iam_user_role_fact "
                    "(fact_uuid, user_id, role_id, role_version, action, actor_user_id, reason_code, "
                    "idempotency_key, occurred_at, created_at) "
                    "VALUES (%s, %s, 1, 1, 'GRANT', %s, 'READER_ACCOUNT_PROVISIONED', %s, %s, %s)",
                    (str(role_fact_uuid), user_id, actor_user_id,
                     f"{idempotency_key}:role:user", now, now),
                )
                await cursor.execute(
                    f"SELECT {_ACCOUNT_COLUMNS} FROM iam_user_account WHERE user_id = %s",
                    (user_id,),
                )
                row = await cursor.fetchone()
            await connection.commit()
            if row is None:
                raise RuntimeError("provisioned account could not be reconciled")
            return AccountProvisioningResult(account=_account(row), activation_code=None)
        except Exception:
            await connection.rollback()
            raise
        finally:
            connection.close()

    async def find_identifier(
        self, identifier_type: IdentifierType, identifier_hash: bytes,
    ) -> LoginIdentifier | None:
        connection = await self._connection_factory()
        try:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "SELECT id, user_id, identifier_type, identifier_hash, display_suffix, "
                    "normalization_version, status, created_at, disabled_at "
                    "FROM iam_login_identifier WHERE identifier_type = %s AND identifier_hash = %s",
                    (identifier_type.value, identifier_hash),
                )
                row = await cursor.fetchone()
            return _identifier(row) if row is not None else None
        finally:
            connection.close()

    async def get_account(self, user_id: int) -> UserAccount | None:
        connection = await self._connection_factory()
        try:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    f"SELECT {_ACCOUNT_COLUMNS} FROM iam_user_account WHERE user_id = %s",
                    (user_id,),
                )
                row = await cursor.fetchone()
            return _account(row) if row is not None else None
        finally:
            connection.close()

    async def get_credential(self, user_id: int) -> PasswordCredential | None:
        connection = await self._connection_factory()
        try:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "SELECT user_id, password_hash, algorithm, parameters_version, password_version, "
                    "changed_at, expires_at, updated_at FROM iam_password_credential WHERE user_id = %s",
                    (user_id,),
                )
                row = await cursor.fetchone()
            return _credential(row) if row is not None else None
        finally:
            connection.close()

    async def set_password_and_activate(
        self, *, user_id: int, credential: PasswordCredential,
        token_hash: bytes, now: datetime,
    ) -> UserAccount:
        connection = await self._connection_factory()
        try:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "SELECT token_uuid, user_id, expires_at, consumed_at, revoked_at "
                    "FROM iam_action_token WHERE purpose = 'ACTIVATE_ACCOUNT' AND token_hash = %s FOR UPDATE",
                    (token_hash,),
                )
                token = await cursor.fetchone()
                timestamp = _db_time(now)
                if (
                    token is None or int(token[1]) != user_id or token[3] is not None
                    or token[4] is not None or _utc(token[2]) <= _utc(now)
                ):
                    raise IdentityError("ACTION_TOKEN_INVALID")
                await cursor.execute(
                    "SELECT status FROM iam_user_account WHERE user_id = %s FOR UPDATE", (user_id,),
                )
                account_state = await cursor.fetchone()
                if account_state is None or account_state[0] != AccountStatus.PENDING_ACTIVATION.value:
                    raise IdentityError("ACCOUNT_NOT_PENDING")
                await cursor.execute(
                    "INSERT INTO iam_password_credential "
                    "(user_id, password_hash, algorithm, parameters_version, password_version, "
                    "changed_at, expires_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    (credential.user_id, credential.password_hash, credential.algorithm,
                     credential.parameters_version, credential.password_version,
                     _db_time(credential.changed_at), _nullable_db_time(credential.expires_at),
                     _db_time(credential.updated_at)),
                )
                await cursor.execute(
                    "UPDATE iam_action_token SET consumed_at = %s "
                    "WHERE token_uuid = %s AND consumed_at IS NULL AND revoked_at IS NULL",
                    (timestamp, str(token[0])),
                )
                if cursor.rowcount != 1:
                    raise IdentityError("ACTION_TOKEN_INVALID")
                await cursor.execute(
                    "UPDATE iam_user_account SET status = 'ACTIVE', must_change_password = FALSE, "
                    "auth_version = auth_version + 1, updated_at = %s WHERE user_id = %s",
                    (timestamp, user_id),
                )
                row = await self._select_account(cursor, user_id)
            await connection.commit()
            return _required_account(row)
        except Exception:
            await connection.rollback()
            raise
        finally:
            connection.close()

    async def update_login_failure(
        self, user_id: int, *, now: datetime, lock_seconds: int, threshold: int,
    ) -> None:
        connection = await self._connection_factory()
        try:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "SELECT failed_login_count FROM iam_user_account WHERE user_id = %s FOR UPDATE",
                    (user_id,),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise IdentityError("ACCOUNT_NOT_FOUND")
                failures = int(row[0]) + 1
                locked_until = None
                if failures >= threshold:
                    failures = 0
                    locked_until = _db_time(now + timedelta(seconds=lock_seconds))
                await cursor.execute(
                    "UPDATE iam_user_account SET failed_login_count = %s, locked_until = %s, "
                    "updated_at = %s WHERE user_id = %s",
                    (failures, locked_until, _db_time(now), user_id),
                )
            await connection.commit()
        except Exception:
            await connection.rollback()
            raise
        finally:
            connection.close()

    async def complete_login(self, user_id: int, *, now: datetime) -> UserAccount:
        connection = await self._connection_factory()
        try:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "UPDATE iam_user_account SET failed_login_count = 0, locked_until = NULL, "
                    "last_login_at = %s, updated_at = %s WHERE user_id = %s AND status = 'ACTIVE'",
                    (_db_time(now), _db_time(now), user_id),
                )
                row = await self._select_account(cursor, user_id)
            await connection.commit()
            return _required_account(row)
        except Exception:
            await connection.rollback()
            raise
        finally:
            connection.close()

    async def effective_roles(self, user_id: int) -> frozenset[RoleCode]:
        connection = await self._connection_factory()
        try:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "SELECT r.role_code FROM iam_effective_user_role_v AS f "
                    "INNER JOIN iam_role AS r ON r.role_id = f.role_id WHERE f.user_id = %s",
                    (user_id,),
                )
                rows = await cursor.fetchall()
            return frozenset(RoleCode(str(row[0])) for row in rows)
        finally:
            connection.close()

    async def create_session(self, session: AuthSession, refresh: RefreshTokenRecord) -> None:
        connection = await self._connection_factory()
        try:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "INSERT INTO iam_auth_session "
                    "(session_uuid, token_family_uuid, user_id, device_type, auth_version_at_issue, "
                    "role_version_at_issue, csrf_secret_hash, issued_at, absolute_expires_at, last_seen_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (str(session.session_uuid), str(session.token_family_uuid), session.user_id,
                     session.device_type, session.auth_version_at_issue, session.role_version_at_issue,
                     session.csrf_secret_hash, _db_time(session.issued_at),
                     _db_time(session.absolute_expires_at), _db_time(session.last_seen_at)),
                )
                await self._insert_refresh(cursor, refresh)
            await connection.commit()
        except Exception:
            await connection.rollback()
            raise
        finally:
            connection.close()

    async def find_refresh(self, token_hash: bytes) -> RefreshTokenRecord | None:
        connection = await self._connection_factory()
        try:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "SELECT token_uuid, session_uuid, token_hash, parent_token_uuid, issued_at, "
                    "expires_at, consumed_at, revoked_at FROM iam_refresh_token WHERE token_hash = %s",
                    (token_hash,),
                )
                row = await cursor.fetchone()
            return _refresh(row) if row is not None else None
        finally:
            connection.close()

    async def get_session(self, session_uuid: UUID) -> AuthSession | None:
        connection = await self._connection_factory()
        try:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "SELECT session_uuid, token_family_uuid, user_id, device_type, auth_version_at_issue, "
                    "role_version_at_issue, csrf_secret_hash, issued_at, absolute_expires_at, last_seen_at, "
                    "revoked_at, revoke_reason FROM iam_auth_session WHERE session_uuid = %s",
                    (str(session_uuid),),
                )
                row = await cursor.fetchone()
            return _session(row) if row is not None else None
        finally:
            connection.close()

    async def rotate_refresh(
        self, *, consumed_uuid: UUID, replacement: RefreshTokenRecord, now: datetime,
    ) -> None:
        connection = await self._connection_factory()
        try:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "SELECT consumed_at, revoked_at FROM iam_refresh_token "
                    "WHERE token_uuid = %s FOR UPDATE",
                    (str(consumed_uuid),),
                )
                row = await cursor.fetchone()
                if row is None or row[0] is not None or row[1] is not None:
                    raise IdentityError("REFRESH_TOKEN_REUSED")
                await cursor.execute(
                    "UPDATE iam_refresh_token SET consumed_at = %s "
                    "WHERE token_uuid = %s AND consumed_at IS NULL AND revoked_at IS NULL",
                    (_db_time(now), str(consumed_uuid)),
                )
                if cursor.rowcount != 1:
                    raise IdentityError("REFRESH_TOKEN_REUSED")
                await self._insert_refresh(cursor, replacement)
                await cursor.execute(
                    "UPDATE iam_auth_session SET last_seen_at = %s "
                    "WHERE session_uuid = %s AND revoked_at IS NULL",
                    (_db_time(now), str(replacement.session_uuid)),
                )
            await connection.commit()
        except Exception:
            await connection.rollback()
            raise
        finally:
            connection.close()

    async def revoke_session(self, session_uuid: UUID, *, reason: str, now: datetime) -> None:
        connection = await self._connection_factory()
        try:
            async with connection.cursor() as cursor:
                await self._revoke_session(cursor, session_uuid, reason=reason, now=now)
            await connection.commit()
        except Exception:
            await connection.rollback()
            raise
        finally:
            connection.close()

    async def revoke_user_sessions(self, user_id: int, *, reason: str, now: datetime) -> None:
        connection = await self._connection_factory()
        try:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "UPDATE iam_auth_session SET revoked_at = COALESCE(revoked_at, %s), "
                    "revoke_reason = COALESCE(revoke_reason, %s) WHERE user_id = %s",
                    (_db_time(now), reason[:64], user_id),
                )
                await cursor.execute(
                    "UPDATE iam_refresh_token AS token INNER JOIN iam_auth_session AS session "
                    "ON session.session_uuid = token.session_uuid "
                    "SET token.revoked_at = COALESCE(token.revoked_at, %s) WHERE session.user_id = %s",
                    (_db_time(now), user_id),
                )
            await connection.commit()
        except Exception:
            await connection.rollback()
            raise
        finally:
            connection.close()

    async def find_action_token(
        self, token_hash: bytes, purpose: ActionTokenPurpose,
    ) -> ActionTokenRecord | None:
        connection = await self._connection_factory()
        try:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "SELECT token_uuid, user_id, purpose, token_hash, issued_by_user_id, expires_at, "
                    "created_at, consumed_at, revoked_at FROM iam_action_token "
                    "WHERE token_hash = %s AND purpose = %s",
                    (token_hash, purpose.value),
                )
                row = await cursor.fetchone()
            return _action_token(row) if row is not None else None
        finally:
            connection.close()

    async def append_action_token(self, token: ActionTokenRecord) -> None:
        connection = await self._connection_factory()
        try:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "INSERT IGNORE INTO iam_action_token "
                    "(token_uuid, user_id, purpose, token_hash, issued_by_user_id, expires_at, "
                    "consumed_at, revoked_at, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (str(token.token_uuid), token.user_id, token.purpose.value, token.token_hash,
                     token.issued_by_user_id, _db_time(token.expires_at),
                     _nullable_db_time(token.consumed_at), _nullable_db_time(token.revoked_at),
                     _db_time(token.created_at)),
                )
                if cursor.rowcount != 1:
                    raise IdentityError("ACTION_TOKEN_CONFLICT")
            await connection.commit()
        except Exception:
            await connection.rollback()
            raise
        finally:
            connection.close()

    async def replace_password(
        self, *, user_id: int, credential: PasswordCredential,
        token_hash: bytes | None, now: datetime,
    ) -> UserAccount:
        connection = await self._connection_factory()
        try:
            async with connection.cursor() as cursor:
                if token_hash is not None:
                    await cursor.execute(
                        "SELECT token_uuid, user_id, expires_at, consumed_at, revoked_at "
                        "FROM iam_action_token WHERE purpose = 'RESET_PASSWORD' AND token_hash = %s FOR UPDATE",
                        (token_hash,),
                    )
                    token = await cursor.fetchone()
                    if (
                        token is None or int(token[1]) != user_id or token[3] is not None
                        or token[4] is not None or _utc(token[2]) <= _utc(now)
                    ):
                        raise IdentityError("ACTION_TOKEN_INVALID")
                    await cursor.execute(
                        "UPDATE iam_action_token SET consumed_at = %s WHERE token_uuid = %s "
                        "AND consumed_at IS NULL AND revoked_at IS NULL",
                        (_db_time(now), str(token[0])),
                    )
                    if cursor.rowcount != 1:
                        raise IdentityError("ACTION_TOKEN_INVALID")
                await cursor.execute(
                    "UPDATE iam_password_credential SET password_hash = %s, algorithm = %s, "
                    "parameters_version = %s, password_version = %s, changed_at = %s, expires_at = %s, "
                    "updated_at = %s WHERE user_id = %s",
                    (credential.password_hash, credential.algorithm, credential.parameters_version,
                     credential.password_version, _db_time(credential.changed_at),
                     _nullable_db_time(credential.expires_at), _db_time(credential.updated_at), user_id),
                )
                if cursor.rowcount != 1:
                    raise IdentityError("CREDENTIAL_NOT_FOUND")
                await cursor.execute(
                    "UPDATE iam_user_account SET auth_version = auth_version + 1, "
                    "must_change_password = FALSE, updated_at = %s WHERE user_id = %s",
                    (_db_time(now), user_id),
                )
                row = await self._select_account(cursor, user_id)
            await connection.commit()
            return _required_account(row)
        except Exception:
            await connection.rollback()
            raise
        finally:
            connection.close()

    async def append_role_fact(self, fact: UserRoleFact) -> tuple[UserAccount, bool]:
        connection = await self._connection_factory()
        try:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "SELECT user_id FROM iam_user_role_fact WHERE idempotency_key = %s",
                    (fact.idempotency_key,),
                )
                prior = await cursor.fetchone()
                if prior is not None:
                    if int(prior[0]) != fact.user_id:
                        raise IdentityError("IDEMPOTENCY_KEY_CONFLICT")
                    row = await self._select_account(cursor, fact.user_id)
                    await connection.rollback()
                    return _required_account(row), True
                await cursor.execute(
                    "SELECT role_version FROM iam_user_account WHERE user_id = %s FOR UPDATE",
                    (fact.user_id,),
                )
                account_row = await cursor.fetchone()
                if account_row is None:
                    raise IdentityError("ACCOUNT_NOT_FOUND")
                version = int(account_row[0]) + 1
                await cursor.execute(
                    "INSERT INTO iam_user_role_fact "
                    "(fact_uuid, user_id, role_id, role_version, action, actor_user_id, reason_code, "
                    "idempotency_key, occurred_at, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (str(fact.fact_uuid), fact.user_id, _ROLE_IDS[fact.role], version,
                     fact.action.value, fact.actor_user_id, fact.reason_code[:64],
                     fact.idempotency_key, _db_time(fact.occurred_at), _db_time(fact.occurred_at)),
                )
                await cursor.execute(
                    "UPDATE iam_user_account SET role_version = %s, updated_at = %s WHERE user_id = %s",
                    (version, _db_time(fact.occurred_at), fact.user_id),
                )
                row = await self._select_account(cursor, fact.user_id)
            await connection.commit()
            return _required_account(row), False
        except Exception:
            await connection.rollback()
            raise
        finally:
            connection.close()

    async def set_account_status(
        self, *, user_id: int, action: AccountStatusAction, reason_code: str,
        idempotency_key: str, event_uuid: UUID, actor_user_id: int, now: datetime,
    ) -> tuple[UserAccount, bool]:
        connection = await self._connection_factory()
        try:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "SELECT user_id, actor_user_id FROM iam_security_event WHERE event_uuid = %s",
                    (str(event_uuid),),
                )
                prior = await cursor.fetchone()
                if prior is not None:
                    if int(prior[0]) != user_id or int(prior[1]) != actor_user_id:
                        raise IdentityError("IDEMPOTENCY_KEY_CONFLICT")
                    row = await self._select_account(cursor, user_id)
                    await connection.rollback()
                    return _required_account(row), True
                await cursor.execute(
                    "SELECT status FROM iam_user_account WHERE user_id = %s FOR UPDATE", (user_id,),
                )
                current = await cursor.fetchone()
                if current is None:
                    raise IdentityError("ACCOUNT_NOT_FOUND")
                if action is AccountStatusAction.ENABLE and current[0] == AccountStatus.PENDING_ACTIVATION.value:
                    raise IdentityError("ACCOUNT_NOT_ACTIVATED")
                status = AccountStatus.ACTIVE if action is AccountStatusAction.ENABLE else AccountStatus.DISABLED
                disabled_reason = None if status is AccountStatus.ACTIVE else reason_code[:64]
                await cursor.execute(
                    "UPDATE iam_user_account SET status = %s, disabled_reason = %s, "
                    "auth_version = auth_version + 1, updated_at = %s WHERE user_id = %s",
                    (status.value, disabled_reason, _db_time(now), user_id),
                )
                metadata = json.dumps(
                    {"idempotency_key_hash": hashlib.sha256(idempotency_key.encode()).hexdigest()},
                    separators=(",", ":"), sort_keys=True,
                )
                await cursor.execute(
                    "INSERT INTO iam_security_event "
                    "(event_uuid, event_type, outcome, user_id, actor_user_id, request_id, reason_code, "
                    "metadata_json, occurred_at, created_at) VALUES (%s, %s, 'SUCCESS', %s, %s, %s, %s, %s, %s, %s)",
                    (str(event_uuid), f"ACCOUNT_{action.value}", user_id, actor_user_id,
                     str(event_uuid), reason_code[:64], metadata, _db_time(now), _db_time(now)),
                )
                row = await self._select_account(cursor, user_id)
            await connection.commit()
            return _required_account(row), False
        except Exception:
            await connection.rollback()
            raise
        finally:
            connection.close()

    async def append_consent(self, fact: ConsentFact) -> None:
        connection = await self._connection_factory()
        try:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "INSERT IGNORE INTO user_personalization_consent_fact "
                    "(consent_uuid, user_id, scope, consent_version, action, policy_version, source, "
                    "evidence_hash, session_uuid, occurred_at, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (str(fact.consent_uuid), fact.user_id, fact.scope.value,
                     fact.consent_version, fact.action.value, fact.policy_version,
                     fact.source, fact.evidence_hash, str(fact.session_uuid),
                     _db_time(fact.occurred_at), _db_time(fact.occurred_at)),
                )
                if cursor.rowcount != 1:
                    await cursor.execute(
                        "SELECT user_id, scope, consent_version, action, policy_version, evidence_hash, "
                        "session_uuid FROM user_personalization_consent_fact WHERE consent_uuid = %s",
                        (str(fact.consent_uuid),),
                    )
                    row = await cursor.fetchone()
                    expected = (
                        fact.user_id, fact.scope.value, fact.consent_version, fact.action.value,
                        fact.policy_version, fact.evidence_hash, str(fact.session_uuid),
                    )
                    if row is None or tuple(row) != expected:
                        raise IdentityError("CONSENT_FACT_CONFLICT")
            await connection.commit()
        except Exception:
            await connection.rollback()
            raise
        finally:
            connection.close()

    async def next_consent_version(self, user_id: int, scope: ConsentScope) -> int:
        connection = await self._connection_factory()
        try:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "SELECT COALESCE(MAX(consent_version), 0) FROM user_personalization_consent_fact "
                    "WHERE user_id = %s AND scope = %s",
                    (user_id, scope.value),
                )
                row = await cursor.fetchone()
            return int(row[0]) + 1
        finally:
            connection.close()

    async def effective_consents(self, user_id: int) -> dict[ConsentScope, bool]:
        result = {scope: False for scope in ConsentScope}
        connection = await self._connection_factory()
        try:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "SELECT scope, action FROM user_effective_personalization_consent_v WHERE user_id = %s",
                    (user_id,),
                )
                rows = await cursor.fetchall()
            for scope, action in rows:
                result[ConsentScope(str(scope))] = str(action) == ConsentAction.GRANT.value
            return result
        finally:
            connection.close()

    async def get_declared_profile(self, user_id: int) -> DeclaredProfile | None:
        connection = await self._connection_factory()
        try:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "SELECT user_id, declared_version, major, grade, research_direction, "
                    "preferred_language, personalization_enabled, updated_at "
                    "FROM user_declared_profile WHERE user_id = %s",
                    (user_id,),
                )
                row = await cursor.fetchone()
            return _declared_profile(row) if row is not None else None
        finally:
            connection.close()

    async def save_declared_profile(
        self, *, user_id: int, major: str | None, grade: str | None,
        research_direction: str | None, preferred_language: str | None,
        personalization_enabled: bool, now: datetime,
    ) -> DeclaredProfile:
        """Append profile history and update only the compatibility projection.

        The history row is immutable.  The one-row current projection is the
        existing, explicitly allowlisted compatibility cache used by the
        recommendation reader; no prior history is updated or deleted.
        """

        connection = await self._connection_factory()
        timestamp = _db_time(now)
        try:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "SELECT user_id, declared_version, major, grade, research_direction, "
                    "preferred_language, personalization_enabled, updated_at "
                    "FROM user_declared_profile WHERE user_id = %s FOR UPDATE",
                    (user_id,),
                )
                prior = await cursor.fetchone()
                if prior is not None:
                    current = _declared_profile(prior)
                    if (
                        current.major, current.grade, current.research_direction,
                        current.preferred_language, current.personalization_enabled,
                    ) == (major, grade, research_direction, preferred_language, personalization_enabled):
                        await connection.rollback()
                        return current
                    version = current.declared_version + 1
                else:
                    version = 1
                await cursor.execute(
                    "INSERT INTO user_declared_profile_history "
                    "(user_id, declared_version, major, grade, research_direction, "
                    "preferred_language, personalization_enabled, valid_from, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (user_id, version, major, grade, research_direction,
                     preferred_language, personalization_enabled, timestamp, timestamp),
                )
                await cursor.execute(
                    "INSERT INTO user_declared_profile "
                    "(user_id, declared_version, major, grade, research_direction, "
                    "preferred_language, personalization_enabled, updated_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON DUPLICATE KEY UPDATE declared_version = VALUES(declared_version), "
                    "major = VALUES(major), grade = VALUES(grade), "
                    "research_direction = VALUES(research_direction), "
                    "preferred_language = VALUES(preferred_language), "
                    "personalization_enabled = VALUES(personalization_enabled), "
                    "updated_at = VALUES(updated_at)",
                    (user_id, version, major, grade, research_direction,
                     preferred_language, personalization_enabled, timestamp),
                )
                await cursor.execute(
                    "SELECT user_id, declared_version, major, grade, research_direction, "
                    "preferred_language, personalization_enabled, updated_at "
                    "FROM user_declared_profile WHERE user_id = %s",
                    (user_id,),
                )
                row = await cursor.fetchone()
            await connection.commit()
            return _required_declared_profile(row)
        except Exception:
            await connection.rollback()
            raise
        finally:
            connection.close()

    async def append_security_event(self, event: SecurityEvent) -> None:
        metadata = json.dumps(event.metadata, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        if len(metadata.encode()) > 2048:
            raise IdentityError("SECURITY_METADATA_TOO_LARGE")
        connection = await self._connection_factory()
        try:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "INSERT IGNORE INTO iam_security_event "
                    "(event_uuid, event_type, outcome, user_id, actor_user_id, session_uuid, "
                    "identifier_hash, request_id, reason_code, metadata_json, occurred_at, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (str(event.event_uuid), event.event_type[:40], event.outcome, event.user_id,
                     event.actor_user_id, str(event.session_uuid) if event.session_uuid else None,
                     event.identifier_hash, str(event.request_id) if event.request_id else None,
                     event.reason_code[:64], metadata or None,
                     _db_time(event.occurred_at), _db_time(event.occurred_at)),
                )
            await connection.commit()
        except Exception:
            await connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    async def _select_account(cursor: Any, user_id: int) -> Any:
        await cursor.execute(
            f"SELECT {_ACCOUNT_COLUMNS} FROM iam_user_account WHERE user_id = %s", (user_id,),
        )
        return await cursor.fetchone()

    @staticmethod
    async def _insert_refresh(cursor: Any, refresh: RefreshTokenRecord) -> None:
        await cursor.execute(
            "INSERT INTO iam_refresh_token "
            "(token_uuid, session_uuid, token_hash, parent_token_uuid, issued_at, expires_at, "
            "consumed_at, revoked_at, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (str(refresh.token_uuid), str(refresh.session_uuid), refresh.token_hash,
             str(refresh.parent_token_uuid) if refresh.parent_token_uuid else None,
             _db_time(refresh.issued_at), _db_time(refresh.expires_at),
             _nullable_db_time(refresh.consumed_at), _nullable_db_time(refresh.revoked_at),
             _db_time(refresh.issued_at)),
        )

    @staticmethod
    async def _revoke_session(cursor: Any, session_uuid: UUID, *, reason: str, now: datetime) -> None:
        await cursor.execute(
            "UPDATE iam_auth_session SET revoked_at = COALESCE(revoked_at, %s), "
            "revoke_reason = COALESCE(revoke_reason, %s) WHERE session_uuid = %s",
            (_db_time(now), reason[:64], str(session_uuid)),
        )
        await cursor.execute(
            "UPDATE iam_refresh_token SET revoked_at = COALESCE(revoked_at, %s) "
            "WHERE session_uuid = %s",
            (_db_time(now), str(session_uuid)),
        )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _db_time(value: datetime) -> datetime:
    return _utc(value).replace(tzinfo=None)


def _nullable_db_time(value: datetime | None) -> datetime | None:
    return _db_time(value) if value is not None else None


def _account(row: Any) -> UserAccount:
    return UserAccount(
        user_id=int(row[0]), account_uuid=UUID(str(row[1])), display_name=str(row[2]),
        account_kind=AccountKind(str(row[3])), status=AccountStatus(str(row[4])),
        auth_version=int(row[5]), role_version=int(row[6]), must_change_password=bool(row[7]),
        failed_login_count=int(row[8]), locked_until=_utc(row[9]) if row[9] else None,
        last_login_at=_utc(row[10]) if row[10] else None, disabled_reason=row[11],
        created_by_user_id=int(row[12]) if row[12] is not None else None,
        created_at=_utc(row[13]), updated_at=_utc(row[14]),
    )


def _required_account(row: Any) -> UserAccount:
    if row is None:
        raise IdentityError("ACCOUNT_NOT_FOUND")
    return _account(row)


def _identifier(row: Any) -> LoginIdentifier:
    return LoginIdentifier(
        identifier_id=int(row[0]), user_id=int(row[1]),
        identifier_type=IdentifierType(str(row[2])), identifier_hash=bytes(row[3]),
        display_suffix=str(row[4]), normalization_version=str(row[5]), status=str(row[6]),
        created_at=_utc(row[7]), disabled_at=_utc(row[8]) if row[8] else None,
    )


def _credential(row: Any) -> PasswordCredential:
    return PasswordCredential(
        user_id=int(row[0]), password_hash=str(row[1]), algorithm=str(row[2]),
        parameters_version=str(row[3]), password_version=int(row[4]),
        changed_at=_utc(row[5]), expires_at=_utc(row[6]) if row[6] else None,
        updated_at=_utc(row[7]),
    )


def _declared_profile(row: Any) -> DeclaredProfile:
    return DeclaredProfile(
        user_id=int(row[0]), declared_version=int(row[1]),
        major=str(row[2]) if row[2] is not None else None,
        grade=str(row[3]) if row[3] is not None else None,
        research_direction=str(row[4]) if row[4] is not None else None,
        preferred_language=str(row[5]) if row[5] is not None else None,
        personalization_enabled=bool(row[6]), updated_at=_utc(row[7]),
    )


def _required_declared_profile(row: Any) -> DeclaredProfile:
    if row is None:
        raise IdentityError("PROFILE_NOT_FOUND")
    return _declared_profile(row)


def _session(row: Any) -> AuthSession:
    return AuthSession(
        session_uuid=UUID(str(row[0])), token_family_uuid=UUID(str(row[1])),
        user_id=int(row[2]), device_type=str(row[3]), auth_version_at_issue=int(row[4]),
        role_version_at_issue=int(row[5]), csrf_secret_hash=bytes(row[6]),
        issued_at=_utc(row[7]), absolute_expires_at=_utc(row[8]), last_seen_at=_utc(row[9]),
        revoked_at=_utc(row[10]) if row[10] else None, revoke_reason=row[11],
    )


def _refresh(row: Any) -> RefreshTokenRecord:
    return RefreshTokenRecord(
        token_uuid=UUID(str(row[0])), session_uuid=UUID(str(row[1])), token_hash=bytes(row[2]),
        parent_token_uuid=UUID(str(row[3])) if row[3] else None,
        issued_at=_utc(row[4]), expires_at=_utc(row[5]),
        consumed_at=_utc(row[6]) if row[6] else None,
        revoked_at=_utc(row[7]) if row[7] else None,
    )


def _action_token(row: Any) -> ActionTokenRecord:
    return ActionTokenRecord(
        token_uuid=UUID(str(row[0])), user_id=int(row[1]),
        purpose=ActionTokenPurpose(str(row[2])), token_hash=bytes(row[3]),
        issued_by_user_id=int(row[4]), expires_at=_utc(row[5]), created_at=_utc(row[6]),
        consumed_at=_utc(row[7]) if row[7] else None,
        revoked_at=_utc(row[8]) if row[8] else None,
    )


__all__ = ["MySQLIdentityRepository"]
