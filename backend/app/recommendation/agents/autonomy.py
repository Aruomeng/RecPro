"""Compatibility exports for the shared Agent autonomy contract.

The implementation lives in ``shared_kernel.contracts.autonomy`` so each
business Agent depends on a common contract rather than another Agent module.
"""

from backend.app.shared_kernel.contracts.autonomy import (
    AgentAutonomyError,
    AgentRoleProfile,
    ROLE_PROFILES,
    assert_payload_decision,
    attach_decision,
    default_decision,
    profile_for,
    validate_decision,
)

__all__ = [
    "AgentAutonomyError",
    "AgentRoleProfile",
    "ROLE_PROFILES",
    "assert_payload_decision",
    "attach_decision",
    "default_decision",
    "profile_for",
    "validate_decision",
]
