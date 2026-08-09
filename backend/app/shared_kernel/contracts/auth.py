"""Transport-neutral authentication facts shared across HTTP and use cases."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    """The minimum trusted identity an adapter may pass into an application port.

    Token parsing and signature verification deliberately stay outside this
    contract.  The composition root injects an authorizer; application code
    receives only the verified subject and roles.  ``roles`` is immutable so a
    request handler cannot accidentally grant itself a new capability.
    """

    user_id: int
    roles: frozenset[str] = field(default_factory=frozenset)
    token_id: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.user_id, bool) or self.user_id < 1:
            raise ValueError("user_id must be a positive integer")
        if not isinstance(self.roles, frozenset):
            raise ValueError("roles must be a frozenset")
        if not all(isinstance(role, str) and role.strip() for role in self.roles):
            raise ValueError("roles must contain non-blank strings")
        if self.token_id is not None and (
            not isinstance(self.token_id, str) or not self.token_id.strip()
        ):
            raise ValueError("token_id must be blank or a non-blank string")

    def has_role(self, role: str) -> bool:
        return role in self.roles


__all__ = ["AuthenticatedPrincipal"]
