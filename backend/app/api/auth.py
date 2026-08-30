"""Authentication boundary for HTTP adapters.

The API deliberately does not decode JWTs or embed a production secret.  A
verified bearer token resolver is injected by the composition root.  Tests and
the local demo may inject a deterministic resolver without changing the
application or persistence layers.
"""

from __future__ import annotations

import inspect
from typing import Awaitable, Callable

from backend.app.api.errors import PublicAPIError
from backend.app.identity.public import RoleCode, has_effective_permission
from backend.app.shared_kernel.contracts.auth import AuthenticatedPrincipal
from backend.app.shared_kernel.contracts.errors import ErrorCode


PrincipalResolution = (
    AuthenticatedPrincipal | None
    | Awaitable[AuthenticatedPrincipal | None]
)
PrincipalResolver = Callable[[str], PrincipalResolution]


def _authentication_error(message: str = "A valid bearer token is required.") -> PublicAPIError:
    return PublicAPIError(
        status_code=401,
        code=ErrorCode.AUTHENTICATION_REQUIRED,
        message=message,
        retryable=False,
        details={},
    )


async def require_bearer_principal(
    authorization: str | None,
    *,
    resolver: PrincipalResolver | None,
) -> AuthenticatedPrincipal:
    """Resolve one bearer token without exposing token or resolver failures."""

    if not authorization:
        raise _authentication_error()
    scheme, separator, token = authorization.partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not token.strip():
        raise _authentication_error("Authorization must use the Bearer scheme.")
    if resolver is None:
        raise _authentication_error()
    try:
        candidate = resolver(token.strip())
        principal = await candidate if inspect.isawaitable(candidate) else candidate
    except Exception as exc:  # pragma: no cover - adapter failures are fail-closed
        raise _authentication_error() from exc
    if not isinstance(principal, AuthenticatedPrincipal):
        raise _authentication_error()
    return principal


async def resolve_user_principal(
    *,
    authorization: str | None,
    demo_user_id: int | None,
    app_env: str,
    demo_identity_enabled: bool,
    resolver: PrincipalResolver | None,
) -> AuthenticatedPrincipal:
    """Resolve formal bearer identity or the explicitly isolated demo identity."""

    if authorization is not None:
        if demo_user_id is not None:
            raise PublicAPIError(
                status_code=403,
                code=ErrorCode.RESOURCE_ACCESS_FORBIDDEN,
                message="Demo identity cannot be combined with bearer authentication.",
                retryable=False,
                details={},
            )
        return await require_bearer_principal(authorization, resolver=resolver)

    if app_env == "demo" and demo_identity_enabled:
        if demo_user_id is None:
            raise _authentication_error("X-Demo-User-Id is required for the local demo.")
        return AuthenticatedPrincipal(user_id=demo_user_id, roles=frozenset({"user"}))

    raise _authentication_error()


def require_permission(
    principal: AuthenticatedPrincipal,
    permission: str,
    *,
    allow_sessionless_demo: bool = False,
) -> None:
    """Fail closed when a route is reached without its capability.

    The only exception is the explicitly isolated synthetic demo identity.
    Guests have no roles and therefore cannot pass this bypass.  Production
    and formal authenticated sessions always use the verified role matrix.
    """

    if (
        allow_sessionless_demo
        and principal.session_id is None
        and principal.has_role(RoleCode.USER.value)
    ):
        return
    if has_effective_permission(principal, permission):
        return
    raise PublicAPIError(
        status_code=403,
        code=ErrorCode.RESOURCE_ACCESS_FORBIDDEN,
        message="The authenticated role cannot perform this action.",
        retryable=False,
        details={"required_permission": permission},
    )


def reject_demo_identity_for_debug(demo_user_id: int | None) -> None:
    """Debug routes must never treat the demo header as an admin credential."""

    if demo_user_id is not None:
        raise PublicAPIError(
            status_code=403,
            code=ErrorCode.RESOURCE_ACCESS_FORBIDDEN,
            message="Research-admin Debug API requires bearer authentication.",
            retryable=False,
            details={},
        )


__all__ = [
    "PrincipalResolver",
    "has_effective_permission",
    "reject_demo_identity_for_debug",
    "require_permission",
    "require_bearer_principal",
    "resolve_user_principal",
]
