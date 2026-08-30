"""Stable public identity boundary for HTTP and composition adapters.

The identity implementation remains free to evolve behind this module.  Other
bounded contexts may depend on these types and capabilities, but must not
import the identity application's internal service or domain modules directly.
"""

from __future__ import annotations

from backend.app.identity.application import IdentityService, consent_evidence_hash
from backend.app.identity.domain import (
    AccountKind,
    AccountStatus,
    AccountStatusAction,
    ActionTokenPurpose,
    ConsentAction,
    ConsentScope,
    DeclaredProfile,
    IdentifierType,
    IdentityError,
    LoginResult,
    RoleAction,
    RoleCode,
    UserAccount,
    ROLE_PERMISSIONS,
)
from backend.app.shared_kernel.contracts.auth import AuthenticatedPrincipal


def has_effective_permission(principal: AuthenticatedPrincipal, permission: str) -> bool:
    """Resolve a verified principal's effective capability in one place."""

    if principal.has_permission(permission):
        return True
    for raw_role in principal.roles:
        try:
            role = RoleCode(raw_role)
        except ValueError:
            continue
        if permission in ROLE_PERMISSIONS.get(role, frozenset()):
            return True
    return False


__all__ = [
    "AccountKind",
    "AccountStatus",
    "AccountStatusAction",
    "ActionTokenPurpose",
    "AuthenticatedPrincipal",
    "ConsentAction",
    "ConsentScope",
    "DeclaredProfile",
    "IdentityError",
    "IdentifierType",
    "IdentityService",
    "LoginResult",
    "RoleAction",
    "RoleCode",
    "UserAccount",
    "consent_evidence_hash",
    "has_effective_permission",
]
