"""Pure clarification-continuation contracts for the opt-in G4 service.

The G4 MySQL adapter must not interpret user answers while it owns a database
transaction.  This module validates the immutable clarification snapshot and
builds the next transport-neutral command without opening a connection,
calling an Agent, or changing any stored fact.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from backend.app.recommendation.domain.public import RecommendationTaskCommand


class G4ClarificationError(ValueError):
    """Clarification input cannot safely continue the G4 task."""


MAX_CLARIFICATION_ANSWER_LENGTH = 500


@dataclass(frozen=True, slots=True)
class G4ClarificationContinuation:
    """Validated answer facts and the command for the next G4 context."""

    command: RecommendationTaskCommand
    answers: Mapping[str, str]
    previous_context_version: int
    context_version: int


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise G4ClarificationError(f"{name} must be a non-blank string")
    return value.strip()


def _question_map(questions: Sequence[object]) -> dict[str, Mapping[str, Any]]:
    mapped: dict[str, Mapping[str, Any]] = {}
    for raw in questions:
        if not isinstance(raw, Mapping):
            raise G4ClarificationError("clarification questions must be JSON objects")
        slot = _required_text(raw.get("slot"), "clarification question.slot")
        if slot in mapped:
            raise G4ClarificationError(f"duplicate clarification slot: {slot}")
        options = raw.get("options")
        if options is not None:
            if not isinstance(options, Sequence) or isinstance(
                options, (str, bytes, bytearray)
            ):
                raise G4ClarificationError(
                    f"clarification options for {slot} must be a list"
                )
            if not options or any(
                not isinstance(option, str) or not option.strip() for option in options
            ):
                raise G4ClarificationError(
                    f"clarification options for {slot} must be non-empty strings"
                )
        mapped[slot] = raw
    if not mapped:
        raise G4ClarificationError("clarification questions must not be empty")
    return mapped


def _validated_answers(
    questions: Sequence[object], answers: Mapping[str, str]
) -> dict[str, str]:
    if not isinstance(answers, Mapping) or not answers:
        raise G4ClarificationError("clarification answers must not be empty")
    question_map = _question_map(questions)
    normalized: dict[str, str] = {}
    for raw_slot, raw_answer in answers.items():
        slot = _required_text(raw_slot, "clarification answer.slot")
        if slot not in question_map:
            raise G4ClarificationError(f"unknown clarification slot: {slot}")
        normalized[slot] = _required_text(
            raw_answer, f"clarification answer.{slot}"
        )
        if len(normalized[slot]) > MAX_CLARIFICATION_ANSWER_LENGTH:
            raise G4ClarificationError(
                f"clarification answer for {slot} exceeds "
                f"{MAX_CLARIFICATION_ANSWER_LENGTH} characters"
            )
        options = question_map[slot].get("options")
        # Options are guided suggestions.  Resource type answers remain
        # closed enums, while the topic slot also accepts bounded custom text
        # (for example, a user may combine several suggested themes with '+').
        if (
            options is not None
            and normalized[slot] not in options
            and slot != "topic"
        ):
            raise G4ClarificationError(
                f"clarification answer for {slot} is not one of the declared options"
            )
    required = {
        slot
        for slot, question in question_map.items()
        if bool(question.get("required", False))
    }
    missing = sorted(required.difference(normalized))
    if missing:
        raise G4ClarificationError(
            "required clarification slots are missing: " + ", ".join(missing)
        )
    return normalized


def _resource_types_from_answer(value: str) -> tuple[str, ...]:
    mapping = {
        "BOOK": ("BOOK",),
        "PAPER": ("PAPER",),
        "BOOK_AND_PAPER": ("BOOK", "PAPER"),
    }
    try:
        return mapping[value]
    except KeyError as exc:
        raise G4ClarificationError(
            "resource_types answer must be BOOK, PAPER, or BOOK_AND_PAPER"
        ) from exc


def build_g4_clarification_continuation(
    command: RecommendationTaskCommand,
    *,
    questions: Sequence[object],
    answers: Mapping[str, str],
    previous_context_version: int,
) -> G4ClarificationContinuation:
    """Validate one waiting context and construct its next G4 command.

    The task/request/session identity, evaluation time, source references,
    constraints, and limit are copied unchanged.  Only explicit clarification
    slots are allowed to affect resource types, topic text, or output type.
    """

    if isinstance(previous_context_version, bool) or previous_context_version < 1:
        raise G4ClarificationError("previous_context_version must be positive")
    validated = _validated_answers(questions, answers)
    resource_types = tuple(command.resource_types)
    if "resource_types" in validated:
        resource_types = _resource_types_from_answer(validated["resource_types"])
    input_text = command.input_text
    if "topic" in validated:
        input_text = validated["topic"]
    output_type = command.output_type
    if "output_type" in validated:
        output_type = validated["output_type"]
    if not resource_types:
        raise G4ClarificationError(
            "clarification continuation must select at least one resource type"
        )
    next_command = RecommendationTaskCommand(
        request_id=command.request_id,
        session_id=command.session_id,
        user_id=command.user_id,
        scene=command.scene,
        input_text=input_text,
        resource_types=resource_types,
        output_type=output_type,
        source_resource_id=command.source_resource_id,
        source_item_id=command.source_item_id,
        evaluation_at=command.evaluation_at,
        constraints=dict(command.constraints),
        limit=command.limit,
    )
    return G4ClarificationContinuation(
        command=next_command,
        answers=dict(validated),
        previous_context_version=previous_context_version,
        context_version=previous_context_version + 1,
    )


__all__ = [
    "G4ClarificationContinuation",
    "G4ClarificationError",
    "build_g4_clarification_continuation",
]
