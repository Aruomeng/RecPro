"""HTTP boundary for local login, administration, and personalization consent."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Cookie, Header, Response
from pydantic import Field

from backend.app.api.auth import PrincipalResolver, require_bearer_principal, require_permission
from backend.app.api.errors import PublicAPIError
from backend.app.api.models import StrictModel
from backend.app.identity.application import IdentityService, consent_evidence_hash
from backend.app.identity.domain import (
    AccountStatusAction,
    ConsentAction,
    ConsentScope,
    DeclaredProfile,
    IdentifierType,
    IdentityError,
    LoginResult,
    RoleAction,
    RoleCode,
    UserAccount,
)
from backend.app.shared_kernel.contracts.auth import AuthenticatedPrincipal
from backend.app.shared_kernel.contracts.errors import ErrorCode


REFRESH_COOKIE = "recpro_refresh"
CSRF_COOKIE = "recpro_csrf"


class LoginRequest(StrictModel):
    identifier_type: IdentifierType
    identifier: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=10, max_length=128)
    device_type: Literal["KIOSK", "BROWSER"] = "KIOSK"


class ActivateRequest(StrictModel):
    identifier_type: IdentifierType
    identifier: str = Field(min_length=3, max_length=64)
    activation_code: str = Field(min_length=16, max_length=256)
    new_password: str = Field(min_length=10, max_length=128)


class PasswordResetCompleteRequest(StrictModel):
    identifier_type: IdentifierType
    identifier: str = Field(min_length=3, max_length=64)
    reset_code: str = Field(min_length=16, max_length=256)
    new_password: str = Field(min_length=10, max_length=128)


class PasswordChangeRequest(StrictModel):
    current_password: str = Field(min_length=10, max_length=128)
    new_password: str = Field(min_length=10, max_length=128)


class CreateReaderRequest(StrictModel):
    display_name: str = Field(min_length=1, max_length=80)
    identifier_type: IdentifierType
    identifier: str = Field(min_length=3, max_length=64)


class StatusActionRequest(StrictModel):
    action: AccountStatusAction
    reason_code: str = Field(min_length=1, max_length=64, pattern=r"^[A-Z0-9_:-]+$")


class RoleActionRequest(StrictModel):
    action: RoleAction
    role: RoleCode
    reason_code: str = Field(min_length=1, max_length=64, pattern=r"^[A-Z0-9_:-]+$")


class ConsentActionRequest(StrictModel):
    scope: ConsentScope
    action: ConsentAction
    policy_version: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._:-]+$")
    source: Literal["LOGIN_ONBOARDING", "SETTINGS"]


class AccountResponse(StrictModel):
    user_id: int = Field(ge=1)
    account_uuid: UUID
    display_name: str
    status: str
    roles: list[RoleCode]
    must_change_password: bool


class LoginResponse(StrictModel):
    access_token: str
    token_type: Literal["Bearer"] = "Bearer"
    expires_in: int = Field(ge=60, le=3600)
    user: AccountResponse
    personalization_consents: dict[ConsentScope, bool]


class MeResponse(StrictModel):
    user: AccountResponse
    permissions: list[str]
    personalization_consents: dict[ConsentScope, bool]
    session_uuid: UUID


class AccountDetailResponse(StrictModel):
    user: AccountResponse
    personalization_consents: dict[ConsentScope, bool]


class OneTimeCodeResponse(StrictModel):
    user: AccountResponse
    purpose: Literal["ACTIVATE_ACCOUNT", "RESET_PASSWORD"]
    one_time_code: str
    displayed_once: Literal[True] = True
    replayed: bool = False


class ConsentResponse(StrictModel):
    personalization_consents: dict[ConsentScope, bool]


class DeclaredProfileRequest(StrictModel):
    major: str | None = Field(default=None, max_length=128)
    grade: str | None = Field(default=None, max_length=32)
    research_direction: str | None = Field(default=None, max_length=255)
    preferred_language: str | None = Field(default=None, max_length=32)


class DeclaredProfileView(StrictModel):
    user_id: int = Field(ge=1)
    declared_version: int = Field(ge=1)
    major: str | None = None
    grade: str | None = None
    research_direction: str | None = None
    preferred_language: str | None = None
    personalization_enabled: bool
    updated_at: datetime


class DeclaredProfileResponse(StrictModel):
    profile: DeclaredProfileView | None = None
    consent_granted: bool


def create_identity_router(
    *, service: IdentityService, principal_resolver: PrincipalResolver,
    secure_cookies: bool = True,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["identity"])

    @router.post("/auth/login", response_model=LoginResponse)
    async def login(payload: LoginRequest, response: Response) -> LoginResponse:
        try:
            result = await service.login(
                identifier_type=payload.identifier_type, identifier=payload.identifier,
                password=payload.password, device_type=payload.device_type,
            )
        except (IdentityError, ValueError) as exc:
            raise _public_identity_error(exc, login=True) from exc
        _set_session_cookies(response, result, secure=secure_cookies)
        return _login_response(result)

    @router.post("/auth/refresh", response_model=LoginResponse)
    async def refresh(
        response: Response,
        refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE)] = None,
        csrf_cookie: Annotated[str | None, Cookie(alias=CSRF_COOKIE)] = None,
        csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
    ) -> LoginResponse:
        if not refresh_token or not csrf_cookie or csrf_header != csrf_cookie:
            raise _auth_error()
        try:
            result = await service.refresh(
                refresh_token=refresh_token, csrf_token=csrf_header,
            )
        except IdentityError as exc:
            raise _auth_error() from exc
        _set_session_cookies(response, result, secure=secure_cookies)
        return _login_response(result)

    @router.post("/auth/logout", status_code=204)
    async def logout(
        response: Response,
        authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    ) -> Response:
        actor = await _verified_actor(service, principal_resolver, authorization)
        try:
            await service.logout(actor)
        except IdentityError as exc:
            raise _auth_error() from exc
        _clear_session_cookies(response, secure=secure_cookies)
        response.status_code = 204
        return response

    @router.get("/auth/me", response_model=MeResponse)
    async def me(
        authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    ) -> MeResponse:
        actor = await _verified_actor(service, principal_resolver, authorization)
        account, roles, consents = await service.account_summary(
            target_user_id=actor.user_id, actor=actor,
        )
        assert actor.session_id is not None
        return MeResponse(
            user=_account_response(account, roles), permissions=sorted(actor.permissions),
            personalization_consents=consents, session_uuid=actor.session_id,
        )

    @router.post("/auth/activate", response_model=AccountResponse)
    async def activate(payload: ActivateRequest) -> AccountResponse:
        try:
            account = await service.activate(
                identifier_type=payload.identifier_type, identifier=payload.identifier,
                activation_code=payload.activation_code, new_password=payload.new_password,
            )
            roles = await _roles_for(service, account.user_id)
            return _account_response(account, roles)
        except (IdentityError, ValueError) as exc:
            raise _public_identity_error(exc) from exc

    @router.post("/auth/password/change", response_model=AccountResponse)
    async def change_password(
        payload: PasswordChangeRequest,
        authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    ) -> AccountResponse:
        actor = await _verified_actor(service, principal_resolver, authorization)
        try:
            account = await service.change_password(
                actor=actor, current_password=payload.current_password,
                new_password=payload.new_password,
            )
            return _account_response(account, await _roles_for(service, account.user_id))
        except (IdentityError, ValueError) as exc:
            raise _public_identity_error(exc, login=True) from exc

    @router.post("/auth/password-reset/complete", response_model=AccountResponse)
    async def complete_reset(payload: PasswordResetCompleteRequest) -> AccountResponse:
        try:
            account = await service.reset_password(
                identifier_type=payload.identifier_type, identifier=payload.identifier,
                reset_code=payload.reset_code, new_password=payload.new_password,
            )
            return _account_response(account, await _roles_for(service, account.user_id))
        except (IdentityError, ValueError) as exc:
            raise _public_identity_error(exc) from exc

    @router.post("/admin/users", response_model=OneTimeCodeResponse, status_code=201)
    async def create_reader(
        payload: CreateReaderRequest,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
        authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    ) -> OneTimeCodeResponse:
        actor = await _verified_actor(service, principal_resolver, authorization)
        try:
            result = await service.provision_reader(
                display_name=payload.display_name, identifier_type=payload.identifier_type,
                identifier=payload.identifier, actor=actor, idempotency_key=idempotency_key,
            )
        except (IdentityError, ValueError) as exc:
            raise _public_identity_error(exc) from exc
        if result.activation_code is None:
            raise PublicAPIError(
                status_code=409, code=ErrorCode.IDEMPOTENCY_KEY_REUSED,
                message="The account request was already completed; its one-time code cannot be displayed again.",
                retryable=False, details={"user_id": result.account.user_id},
            )
        return OneTimeCodeResponse(
            user=_account_response(result.account, frozenset({RoleCode.USER})),
            purpose="ACTIVATE_ACCOUNT", one_time_code=result.activation_code,
            replayed=result.replayed,
        )

    @router.get("/admin/users/{user_id}", response_model=AccountDetailResponse)
    async def read_user(
        user_id: int,
        authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    ) -> AccountDetailResponse:
        actor = await _verified_actor(service, principal_resolver, authorization)
        try:
            account, roles, consents = await service.account_summary(
                target_user_id=user_id, actor=actor,
            )
        except IdentityError as exc:
            raise _public_identity_error(exc) from exc
        return AccountDetailResponse(
            user=_account_response(account, roles),
            personalization_consents=consents,
        )

    @router.post("/admin/users/{user_id}/activation-codes", response_model=OneTimeCodeResponse)
    async def activation_code(
        user_id: int,
        authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    ) -> OneTimeCodeResponse:
        actor = await _verified_actor(service, principal_resolver, authorization)
        try:
            code = await service.issue_activation_code(target_user_id=user_id, actor=actor)
            account, roles, _ = await service.account_summary(target_user_id=user_id, actor=actor)
        except IdentityError as exc:
            raise _public_identity_error(exc) from exc
        return OneTimeCodeResponse(
            user=_account_response(account, roles), purpose="ACTIVATE_ACCOUNT",
            one_time_code=code,
        )

    @router.post("/admin/users/{user_id}/password-reset-codes", response_model=OneTimeCodeResponse)
    async def reset_code(
        user_id: int,
        authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    ) -> OneTimeCodeResponse:
        actor = await _verified_actor(service, principal_resolver, authorization)
        try:
            code = await service.issue_password_reset_code(target_user_id=user_id, actor=actor)
            account, roles, _ = await service.account_summary(target_user_id=user_id, actor=actor)
        except IdentityError as exc:
            raise _public_identity_error(exc) from exc
        return OneTimeCodeResponse(
            user=_account_response(account, roles), purpose="RESET_PASSWORD",
            one_time_code=code,
        )

    @router.post("/admin/users/{user_id}/status-actions", response_model=AccountResponse)
    async def status_action(
        user_id: int, payload: StatusActionRequest,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
        authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    ) -> AccountResponse:
        actor = await _verified_actor(service, principal_resolver, authorization)
        try:
            account = await service.status_action(
                target_user_id=user_id, action=payload.action, actor=actor,
                reason_code=payload.reason_code, idempotency_key=idempotency_key,
            )
            return _account_response(account, await _roles_for(service, user_id))
        except IdentityError as exc:
            raise _public_identity_error(exc) from exc

    @router.post("/admin/users/{user_id}/role-actions", response_model=AccountResponse)
    async def role_action(
        user_id: int, payload: RoleActionRequest,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
        authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    ) -> AccountResponse:
        actor = await _verified_actor(service, principal_resolver, authorization)
        try:
            account = await service.role_action(
                target_user_id=user_id, role=payload.role, action=payload.action,
                actor=actor, reason_code=payload.reason_code,
                idempotency_key=idempotency_key,
            )
            return _account_response(account, await _roles_for(service, user_id))
        except IdentityError as exc:
            raise _public_identity_error(exc) from exc

    @router.get("/me/personalization-consents", response_model=ConsentResponse)
    async def read_consents(
        authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    ) -> ConsentResponse:
        actor = await _verified_actor(service, principal_resolver, authorization)
        require_permission(actor, "profile.self.read")
        _, _, consents = await service.account_summary(target_user_id=actor.user_id, actor=actor)
        return ConsentResponse(personalization_consents=consents)

    @router.post("/me/personalization-consents", response_model=ConsentResponse)
    async def write_consent(
        payload: ConsentActionRequest,
        authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    ) -> ConsentResponse:
        actor = await _verified_actor(service, principal_resolver, authorization)
        require_permission(actor, "profile.self.update")
        try:
            consents = await service.consent_action(
                scope=payload.scope, action=payload.action,
                policy_version=payload.policy_version, source=payload.source,
                evidence_hash=consent_evidence_hash(
                    policy_version=payload.policy_version, scope=payload.scope,
                    action=payload.action,
                ),
                actor=actor,
            )
        except IdentityError as exc:
            raise _public_identity_error(exc) from exc
        return ConsentResponse(personalization_consents=consents)

    @router.get("/me/profile", response_model=DeclaredProfileResponse)
    async def read_declared_profile(
        authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    ) -> DeclaredProfileResponse:
        actor = await _verified_actor(service, principal_resolver, authorization)
        try:
            profile, consent_granted = await service.read_declared_profile(actor=actor)
        except (IdentityError, ValueError) as exc:
            raise _public_identity_error(exc) from exc
        return DeclaredProfileResponse(
            profile=_declared_profile_view(profile) if profile is not None else None,
            consent_granted=consent_granted,
        )

    @router.put("/me/declared-profile", response_model=DeclaredProfileResponse)
    async def update_declared_profile(
        payload: DeclaredProfileRequest,
        authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    ) -> DeclaredProfileResponse:
        actor = await _verified_actor(service, principal_resolver, authorization)
        try:
            profile = await service.update_declared_profile(
                actor=actor,
                major=payload.major,
                grade=payload.grade,
                research_direction=payload.research_direction,
                preferred_language=payload.preferred_language,
            )
        except (IdentityError, ValueError) as exc:
            raise _public_identity_error(exc) from exc
        return DeclaredProfileResponse(
            profile=_declared_profile_view(profile), consent_granted=True,
        )

    return router


async def _verified_actor(
    service: IdentityService, resolver: PrincipalResolver, authorization: str | None,
) -> AuthenticatedPrincipal:
    principal = await require_bearer_principal(authorization, resolver=resolver)
    try:
        return await service.validate_principal(principal)
    except IdentityError as exc:
        raise _auth_error() from exc


async def _roles_for(service: IdentityService, user_id: int) -> frozenset[RoleCode]:
    synthetic_actor = AuthenticatedPrincipal(
        user_id=user_id, roles=frozenset({RoleCode.USER.value}),
    )
    account, roles, _ = await service.account_summary(target_user_id=user_id, actor=synthetic_actor)
    del account
    return roles


def _account_response(account: UserAccount, roles: frozenset[RoleCode]) -> AccountResponse:
    return AccountResponse(
        user_id=account.user_id, account_uuid=account.account_uuid,
        display_name=account.display_name, status=account.status.value,
        roles=sorted(roles, key=lambda role: role.value),
        must_change_password=account.must_change_password,
    )


def _declared_profile_view(profile: DeclaredProfile) -> DeclaredProfileView:
    return DeclaredProfileView(
        user_id=profile.user_id,
        declared_version=profile.declared_version,
        major=profile.major,
        grade=profile.grade,
        research_direction=profile.research_direction,
        preferred_language=profile.preferred_language,
        personalization_enabled=profile.personalization_enabled,
        updated_at=profile.updated_at,
    )


def _login_response(result: LoginResult) -> LoginResponse:
    return LoginResponse(
        access_token=result.access_token, expires_in=result.expires_in,
        user=_account_response(result.account, result.roles),
        personalization_consents=result.consents,
    )


def _set_session_cookies(response: Response, result: LoginResult, *, secure: bool) -> None:
    response.set_cookie(
        REFRESH_COOKIE, result.refresh_token, max_age=8 * 60 * 60,
        httponly=True, secure=secure, samesite="strict", path="/api/v1/auth",
    )
    response.set_cookie(
        CSRF_COOKIE, result.csrf_token, max_age=8 * 60 * 60,
        httponly=False, secure=secure, samesite="strict", path="/",
    )


def _clear_session_cookies(response: Response, *, secure: bool) -> None:
    response.delete_cookie(
        REFRESH_COOKIE, httponly=True, secure=secure, samesite="strict",
        path="/api/v1/auth",
    )
    response.delete_cookie(
        CSRF_COOKIE, httponly=False, secure=secure, samesite="strict",
        path="/",
    )


def _auth_error() -> PublicAPIError:
    return PublicAPIError(
        status_code=401, code=ErrorCode.AUTHENTICATION_REQUIRED,
        message="The credentials or session are invalid.", retryable=False, details={},
    )


def _public_identity_error(exc: Exception, *, login: bool = False) -> PublicAPIError:
    code = exc.code if isinstance(exc, IdentityError) else "INVALID_INPUT"
    if login or code in {"INVALID_CREDENTIALS", "AUTHENTICATION_INVALID"}:
        return _auth_error()
    if code in {"ROLE_REQUIRED", "TARGET_ROLE_FORBIDDEN", "SELF_STATUS_CHANGE_FORBIDDEN", "SERVICE_ROLE_BROWSER_ASSIGNMENT_FORBIDDEN", "PERSONALIZATION_CONSENT_REQUIRED"}:
        return PublicAPIError(
            status_code=403, code=ErrorCode.RESOURCE_ACCESS_FORBIDDEN,
            message="The authenticated role cannot perform this action.",
            retryable=False, details={},
        )
    if code == "USER_SESSION_REQUIRED":
        return _auth_error()
    if code == "PROFILE_NOT_FOUND":
        return PublicAPIError(
            status_code=404, code=ErrorCode.NOT_FOUND,
            message="The declared profile was not found.", retryable=False, details={},
        )
    if code == "ACCOUNT_NOT_FOUND":
        return PublicAPIError(
            status_code=404, code=ErrorCode.NOT_FOUND,
            message="The account was not found.", retryable=False, details={},
        )
    if code in {"IDENTIFIER_ALREADY_EXISTS", "IDEMPOTENCY_KEY_CONFLICT", "ACCOUNT_NOT_PENDING"}:
        return PublicAPIError(
            status_code=409, code=ErrorCode.IDEMPOTENCY_KEY_REUSED,
            message="The account action conflicts with existing identity state.",
            retryable=False, details={},
        )
    return PublicAPIError(
        status_code=400, code=ErrorCode.INVALID_JSON,
        message="The identity request could not be completed.", retryable=False, details={},
    )


__all__ = ["create_identity_router", "REFRESH_COOKIE", "CSRF_COOKIE"]
