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
_ALLOWED_OUTPUT_TYPES = frozenset({"TOPIC_RESOURCES", "READING_PATH"})


def _validate_output_limit(*, output_type: object, limit: object, label: str) -> None:
    if not isinstance(output_type, str) or output_type not in _ALLOWED_OUTPUT_TYPES:
        raise ValueError(f"{label} output_type is not an approved G4 output type")
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError(f"{label} limit must be an integer")
    minimum = 6 if output_type == "READING_PATH" else 1
    if not minimum <= limit <= 20:
        raise ValueError(f"{label} limit is outside the approved output-type bounds")


def validate_g4_projection_query_spec(value: object) -> dict[str, Any]:
    """Validate semantic request fields while allowing bounded verifier metadata."""

    if not isinstance(value, Mapping):
        raise ValueError("G4 baseline query_spec must be an object")
    required = set(EXPECTED_G4_QUERY_SPEC)
    if set(value) - required - _ALLOWED_METADATA_FIELDS:
        unknown = set(value) - required - _ALLOWED_METADATA_FIELDS
        raise ValueError(
            "G4 baseline query_spec contains unsupported fields: "
            + ", ".join(sorted(str(item) for item in unknown))
        )
    if set(value) & required != required:
        raise ValueError("G4 baseline query_spec is missing semantic request fields")
    input_text = value.get("input_text")
    if not isinstance(input_text, str) or not input_text.strip() or len(input_text) > 2000:
        raise ValueError("G4 baseline input_text must contain 1-2000 characters")
    if value.get("resource_types") != ["BOOK"]:
        raise ValueError("G4 baseline resource_types are not the approved BOOK set")
    _validate_output_limit(
        output_type=value.get("output_type"),
        limit=value.get("limit"),
        label="G4 baseline",
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
    _validate_output_limit(
        output_type=output_type,
        limit=limit,
        label="planned HTTP request",
    )
    expected_semantics = {
        "input_text": str(validated["input_text"]).strip(),
        "resource_types": validated["resource_types"],
        "output_type": validated["output_type"],
        "limit": validated["limit"],
    }
    if request_semantics != expected_semantics:
        raise ValueError("planned HTTP request does not match the G4 recall evidence")
    return validated


__all__ = [
    "EXPECTED_G4_QUERY_SPEC",
    "validate_g4_projection_query_spec",
    "validate_g4_projection_request_matches_query_spec",
]
