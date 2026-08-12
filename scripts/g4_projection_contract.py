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


def validate_g4_projection_request_matches_query_spec(
    query_spec: object,
    *,
    input_text: str,
    resource_types: list[str],
    output_type: str,
    limit: int,
) -> dict[str, Any]:
    """Fail closed when a planned HTTP request differs from its recall evidence."""

    validated = validate_g4_projection_query_spec(query_spec)
    request_semantics = {
        "input_text": input_text.strip(),
        "resource_types": resource_types,
        "output_type": output_type,
        "limit": limit,
    }
    expected_semantics = {key: validated[key] for key in EXPECTED_G4_QUERY_SPEC}
    if request_semantics != expected_semantics:
        raise ValueError("planned HTTP request does not match the G4 recall evidence")
    return validated


__all__ = [
    "EXPECTED_G4_QUERY_SPEC",
    "validate_g4_projection_query_spec",
    "validate_g4_projection_request_matches_query_spec",
]
