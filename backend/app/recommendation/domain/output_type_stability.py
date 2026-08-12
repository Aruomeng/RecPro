"""Pure output-type inference and session hysteresis rules.

The policy Agent receives the previous session decision as structured context,
then calls these functions without opening a persistence boundary or consulting
another Agent.  Keeping the state transition here makes the two-round hold and
the explicit-intent escape hatch independently testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from backend.app.shared_kernel.contracts.enums import OutputType


_VALID_OUTPUT_TYPES = frozenset(item.value for item in OutputType)
DEFAULT_TOPIC_FOCUS_INFER_THRESHOLD = 0.65
DEFAULT_HYSTERESIS_MARGIN = 0.05
DEFAULT_MIN_OUTPUT_TYPE_ROUNDS = 2
_TOPIC_INTENTS = frozenset(
    {
        "TOPIC_RECOMMENDATION",
        "PAPER_RECOMMENDATION",
        "BOOK_RECOMMENDATION",
    }
)


def _output_type(value: object, field_name: str) -> str:
    if isinstance(value, OutputType):
        normalized = value.value
    elif isinstance(value, str):
        normalized = value.strip().upper()
    else:
        raise ValueError(f"{field_name} must be a valid OutputType")
    if normalized not in _VALID_OUTPUT_TYPES:
        raise ValueError(f"{field_name} is not a supported OutputType: {normalized!r}")
    return normalized


def _bounded_signal(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be numeric")
    signal = float(value)
    if not isfinite(signal) or not 0.0 <= signal <= 1.0:
        raise ValueError(f"{field_name} must be finite and between 0 and 1")
    return signal


def _threshold(value: object, field_name: str) -> float:
    return _bounded_signal(value, field_name)


def _round_count(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


@dataclass(frozen=True, slots=True)
class OutputTypeStabilityDecision:
    """The append-only state transition produced for one policy round."""

    output_type: str
    reason_code: str
    changed: bool
    rounds: int
    explicit_override: bool

    def __post_init__(self) -> None:
        if self.output_type not in _VALID_OUTPUT_TYPES:
            raise ValueError("output_type must be a supported OutputType")
        if not isinstance(self.reason_code, str) or not self.reason_code.strip():
            raise ValueError("reason_code must be non-blank")
        if not isinstance(self.changed, bool):
            raise ValueError("changed must be boolean")
        if not isinstance(self.rounds, int) or isinstance(self.rounds, bool) or self.rounds < 1:
            raise ValueError("rounds must be a positive integer")
        if not isinstance(self.explicit_override, bool):
            raise ValueError("explicit_override must be boolean")


def infer_auto_output_type(
    *,
    intent_type: object,
    topic_focus_strength: object,
    topic_focus_infer_threshold: object = DEFAULT_TOPIC_FOCUS_INFER_THRESHOLD,
) -> str:
    """Map structured intent/profile signals to an automatic output type."""

    intent = str(intent_type or "").strip().upper()
    strength = _bounded_signal(topic_focus_strength, "topic_focus_strength")
    threshold = _threshold(topic_focus_infer_threshold, "topic_focus_infer_threshold")
    if intent == "BOOKLIST_RECOMMENDATION":
        return OutputType.BOOKLIST.value
    if intent == "READING_PATH_RECOMMENDATION":
        return OutputType.READING_PATH.value
    if intent in _TOPIC_INTENTS:
        return OutputType.TOPIC_RESOURCES.value
    if intent == "GENERAL_RECOMMENDATION" and strength >= threshold:
        return OutputType.TOPIC_RESOURCES.value
    return OutputType.PERSONALIZED_FEED.value


def stabilize_output_type(
    *,
    proposed_output_type: object,
    topic_focus_strength: object,
    previous_output_type: object | None = None,
    previous_rounds: object = 0,
    explicit_output_type: object | None = None,
    topic_focus_infer_threshold: object = DEFAULT_TOPIC_FOCUS_INFER_THRESHOLD,
    hysteresis_margin: object = DEFAULT_HYSTERESIS_MARGIN,
    min_output_type_rounds: object = DEFAULT_MIN_OUTPUT_TYPE_ROUNDS,
) -> OutputTypeStabilityDecision:
    """Apply explicit override, minimum hold, then threshold hysteresis.

    ``previous_rounds`` is the number of consecutive rounds represented by the
    previous output type.  A changed automatic proposal is held until that
    count reaches ``min_output_type_rounds``; it is also held while the signal
    remains in the configured threshold band.
    """

    proposed = _output_type(proposed_output_type, "proposed_output_type")
    previous = (
        _output_type(previous_output_type, "previous_output_type")
        if previous_output_type is not None
        else None
    )
    rounds = _round_count(previous_rounds, "previous_rounds")
    strength = _bounded_signal(topic_focus_strength, "topic_focus_strength")
    threshold = _threshold(topic_focus_infer_threshold, "topic_focus_infer_threshold")
    margin = _threshold(hysteresis_margin, "hysteresis_margin")
    minimum = _round_count(min_output_type_rounds, "min_output_type_rounds")
    if minimum < 1:
        raise ValueError("min_output_type_rounds must be at least 1")
    if threshold - margin < 0.0 or threshold + margin > 1.0:
        raise ValueError("hysteresis band must stay within [0, 1]")

    if explicit_output_type is not None and str(explicit_output_type).strip():
        explicit = _output_type(explicit_output_type, "explicit_output_type")
        changed = previous is None or explicit != previous
        return OutputTypeStabilityDecision(
            output_type=explicit,
            reason_code="EXPLICIT_OUTPUT_TYPE_OVERRIDE",
            changed=changed,
            rounds=(1 if changed or previous is None else rounds + 1),
            explicit_override=True,
        )

    if previous is None:
        return OutputTypeStabilityDecision(
            output_type=proposed,
            reason_code="AUTO_OUTPUT_TYPE_INITIAL",
            changed=True,
            rounds=1,
            explicit_override=False,
        )
    if proposed == previous:
        return OutputTypeStabilityDecision(
            output_type=previous,
            reason_code="AUTO_OUTPUT_TYPE_STABLE",
            changed=False,
            rounds=max(1, rounds) + 1,
            explicit_override=False,
        )
    if rounds < minimum:
        return OutputTypeStabilityDecision(
            output_type=previous,
            reason_code="AUTO_OUTPUT_TYPE_HOLD_MIN_ROUNDS",
            changed=False,
            rounds=rounds + 1,
            explicit_override=False,
        )
    if threshold - margin <= strength <= threshold + margin:
        return OutputTypeStabilityDecision(
            output_type=previous,
            reason_code="AUTO_OUTPUT_TYPE_HYSTERESIS_HOLD",
            changed=False,
            rounds=rounds + 1,
            explicit_override=False,
        )
    return OutputTypeStabilityDecision(
        output_type=proposed,
        reason_code="AUTO_OUTPUT_TYPE_SWITCH",
        changed=True,
        rounds=1,
        explicit_override=False,
    )


__all__ = [
    "DEFAULT_HYSTERESIS_MARGIN",
    "DEFAULT_MIN_OUTPUT_TYPE_ROUNDS",
    "DEFAULT_TOPIC_FOCUS_INFER_THRESHOLD",
    "OutputTypeStabilityDecision",
    "infer_auto_output_type",
    "stabilize_output_type",
]
