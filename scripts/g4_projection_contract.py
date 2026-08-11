"""Shared, bounded G4 projection request contract validation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


EXPECTED_G4_QUERY_SPEC: dict[str, object] = {
    "input_text": "多智能体系统与智慧图书馆",
    "resource_types": ["BOOK"],
    "output_type": "TOPIC_RESOURCES",
    "limit": 8,
}
_ALLOWED_METADATA_FIELDS = frozenset({"deadline_seconds"})


def validate_g4_projection_query_spec(value: object) -> dict[str, Any]:
    """Validate semantic request fields while allowing bounded verifier metadata."""

    if not isinstance(value, Mapping):
        raise ValueError("G4 baseline query_spec must be an object")
    for key, expected in EXPECTED_G4_QUERY_SPEC.items():
        if value.get(key) != expected:
            raise ValueError("G4 baseline query_spec does not match the approved request")
    unknown = set(value) - set(EXPECTED_G4_QUERY_SPEC) - _ALLOWED_METADATA_FIELDS
    if unknown:
        raise ValueError(
            "G4 baseline query_spec contains unsupported fields: "
            + ", ".join(sorted(str(item) for item in unknown))
        )
    if "deadline_seconds" in value:
        deadline = value["deadline_seconds"]
        if (
            isinstance(deadline, bool)
            or not isinstance(deadline, (int, float))
            or not 30 <= float(deadline) <= 300
        ):
            raise ValueError("G4 baseline deadline_seconds must be between 30 and 300")
    return dict(value)


__all__ = ["EXPECTED_G4_QUERY_SPEC", "validate_g4_projection_query_spec"]
