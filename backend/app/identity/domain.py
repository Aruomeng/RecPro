"""Transport- and storage-neutral IAM domain records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


class AccountKind(StrEnum):
    HUMAN = "HUMAN"
    SERVICE = "SERVICE"


class AccountStatus(StrEnum):
    PENDING_ACTIVATION = "PENDING_ACTIVATION"
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class IdentifierType(StrEnum):
    READER_NUMBER = "READER_NUMBER"
    STUDENT_NUMBER = "STUDENT_NUMBER"


class RoleCode(StrEnum):
    USER = "user"
    LIBRARIAN = "librarian"
    RESEARCH_ADMIN = "research_admin"
    SERVICE_WORKER = "service_worker"


class ConsentScope(StrEnum):
    DECLARED_PROFILE = "DECLARED_PROFILE"
    BEHAVIOR_LEARNING = "BEHAVIOR_LEARNING"
    PERSONALIZED_RECOMMENDATION = "PERSONALIZED_RECOMMENDATION"
    RESEARCH_ANALYTICS = "RESEARCH_ANALYTICS"


class ConsentAction(StrEnum):
    GRANT = "GRANT"
    WITHDRAW = "WITHDRAW"


class RoleAction(StrEnum):
    GRANT = "GRANT"
    REVOKE = "REVOKE"


class AccountStatusAction(StrEnum):
    ENABLE = "ENABLE"
    DISABLE = "DISABLE"


class ActionTokenPurpose(StrEnum):
    ACTIVATE_ACCOUNT = "ACTIVATE_ACCOUNT"
    RESET_PASSWORD = "RESET_PASSWORD"


class IdentityError(RuntimeError):
    """Stable internal error code; HTTP adapters decide the public message."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(slots=True)
class UserAccount:
    user_id: int
    account_uuid: UUID
    display_name: str
    account_kind: AccountKind
    status: AccountStatus
    auth_version: int
    role_version: int
    must_change_password: bool
    failed_login_count: int
    locked_until: datetime | None
    last_login_at: datetime | None
    disabled_reason: str | None
    created_by_user_id: int | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class LoginIdentifier:
    identifier_id: int
    user_id: int
    identifier_type: IdentifierType
    identifier_hash: bytes
    display_suffix: str
    normalization_version: str
    status: str
    created_at: datetime
    disabled_at: datetime | None = None


@dataclass(slots=True)
class PasswordCredential:
    user_id: int
    password_hash: str
    algorithm: str
    parameters_version: str
    password_version: int
    changed_at: datetime
    expires_at: datetime | None
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class UserRoleFact:
    fact_uuid: UUID
    user_id: int
    role: RoleCode
    role_version: int
    action: RoleAction
    actor_user_id: int
    reason_code: str
    idempotency_key: str
    occurred_at: datetime


@dataclass(slots=True)
class AuthSession:
    session_uuid: UUID
    token_family_uuid: UUID
    user_id: int
    device_type: str
    auth_version_at_issue: int
    role_version_at_issue: int
    csrf_secret_hash: bytes
    issued_at: datetime
    absolute_expires_at: datetime
    last_seen_at: datetime
    revoked_at: datetime | None = None
    revoke_reason: str | None = None


@dataclass(slots=True)
class RefreshTokenRecord:
    token_uuid: UUID
    session_uuid: UUID
    token_hash: bytes
    parent_token_uuid: UUID | None
    issued_at: datetime
    expires_at: datetime
    consumed_at: datetime | None = None
    revoked_at: datetime | None = None


@dataclass(slots=True)
class ActionTokenRecord:
    token_uuid: UUID
    user_id: int
    purpose: ActionTokenPurpose
    token_hash: bytes
    issued_by_user_id: int
    expires_at: datetime
    created_at: datetime
    consumed_at: datetime | None = None
    revoked_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class SecurityEvent:
    event_uuid: UUID
    event_type: str
    outcome: str
    user_id: int | None
    actor_user_id: int | None
    session_uuid: UUID | None
    identifier_hash: bytes | None
    request_id: UUID | None
    reason_code: str
    occurred_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ConsentFact:
    consent_uuid: UUID
    user_id: int
    scope: ConsentScope
    consent_version: int
    action: ConsentAction
    policy_version: str
    source: str
    evidence_hash: str
    session_uuid: UUID
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class LoginResult:
    access_token: str
    expires_in: int
    refresh_token: str
    csrf_token: str
    session_uuid: UUID
    account: UserAccount
    roles: frozenset[RoleCode]
    consents: dict[ConsentScope, bool]


@dataclass(frozen=True, slots=True)
class AccountProvisioningResult:
    account: UserAccount
    activation_code: str | None
    replayed: bool = False


ROLE_PERMISSIONS: dict[RoleCode, frozenset[str]] = {
    RoleCode.USER: frozenset({
        "catalog.read", "recommendation.self.execute", "workspace.self.use",
        "profile.self.read", "profile.self.update", "feedback.self.write",
    }),
    RoleCode.LIBRARIAN: frozenset({
        "catalog.read", "account.reader.create", "account.reader.read",
        "account.reader.disable", "account.reader.reset_password",
        "catalog.knowledge.review",
    }),
    RoleCode.RESEARCH_ADMIN: frozenset({
        "catalog.read", "role.assign", "research.trace.read",
        "research.profile.replay", "research.audit.read",
        "catalog.knowledge.review",
    }),
    RoleCode.SERVICE_WORKER: frozenset({"worker.profile.consume"}),
}


__all__ = [name for name in globals() if not name.startswith("_")]
