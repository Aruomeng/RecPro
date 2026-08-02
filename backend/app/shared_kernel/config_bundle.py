"""Framework-independent parsing and semantic rules for config Bundles."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, NoReturn


@dataclass(frozen=True, slots=True)
class ConfigBundleSemanticIssue:
    code: str
    detail: str


def _reject_non_finite_constant(value: str) -> NoReturn:
    raise ValueError(f"non-finite JSON constant is forbidden: {value}")


def load_strict_json(source: str | bytes | bytearray) -> Any:
    """Parse RFC-compatible JSON while rejecting NaN and infinities."""

    return json.loads(source, parse_constant=_reject_non_finite_constant)


def _contains_non_finite(value: Any) -> bool:
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, Mapping):
        return any(_contains_non_finite(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_non_finite(item) for item in value)
    return False


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        normalized = float(value)
    except (OverflowError, ValueError):
        return None
    return normalized if math.isfinite(normalized) else None


def _require_sum_one(
    values: Any,
    label: str,
    issues: list[ConfigBundleSemanticIssue],
) -> None:
    if isinstance(values, Mapping):
        members = list(values.values())
    elif isinstance(values, list):
        members = values
    else:
        issues.append(
            ConfigBundleSemanticIssue(
                "WEIGHT_CONTAINER_INVALID",
                f"{label} is not a collection",
            )
        )
        return
    numeric = [_number(value) for value in members]
    if any(value is None for value in numeric):
        issues.append(
            ConfigBundleSemanticIssue(
                "WEIGHT_NOT_NUMERIC",
                f"{label} contains non-numeric or non-finite values",
            )
        )
        return
    total = sum(value for value in numeric if value is not None)
    if not math.isfinite(total) or abs(total - 1.0) > 1e-9:
        issues.append(
            ConfigBundleSemanticIssue(
                "WEIGHT_SUM_INVALID",
                f"{label} sums to {total:.12g}, expected 1",
            )
        )


def validate_config_bundle_semantics(
    config: Any,
) -> tuple[ConfigBundleSemanticIssue, ...]:
    """Validate cross-field rules that JSON Schema cannot express."""

    issues: list[ConfigBundleSemanticIssue] = []
    if not isinstance(config, Mapping):
        return (
            ConfigBundleSemanticIssue(
                "CONFIG_CONTRACT_INVALID",
                "config must be an object",
            ),
        )
    if _contains_non_finite(config):
        issues.append(
            ConfigBundleSemanticIssue(
                "CONFIG_NON_FINITE_NUMBER",
                "config contains NaN or an infinite number",
            )
        )

    try:
        for resource_type in ("book", "paper"):
            _require_sum_one(
                config["ranking"][resource_type],
                f"ranking.{resource_type}",
                issues,
            )
        for intent_mode in ("general", "explicit"):
            _require_sum_one(
                config["rrf"][intent_mode],
                f"rrf.{intent_mode}",
                issues,
            )
        _require_sum_one(
            config["diversity"]["general_book_paper_ratio"],
            "diversity.general_book_paper_ratio",
            issues,
        )

        formula = config["formula_constants"]
        profile_confidence = {
            key: formula["profile_confidence"][key]
            for key in ("volume", "source_diversity", "stability", "declared_metadata")
        }
        _require_sum_one(
            profile_confidence,
            "formula_constants.profile_confidence",
            issues,
        )
        for formula_name in (
            "probe_match",
            "run_evidence",
            "item_evidence",
            "pre_plan_pipeline_health",
            "intent_score",
            "feedback_score",
            "mmr_similarity",
        ):
            _require_sum_one(
                formula[formula_name],
                f"formula_constants.{formula_name}",
                issues,
            )

        policy = config["policy"]
        if policy["evidence_degraded_threshold"] > policy["evidence_detailed_threshold"]:
            issues.append(
                ConfigBundleSemanticIssue(
                    "POLICY_THRESHOLD_ORDER_INVALID",
                    "evidence_degraded_threshold exceeds evidence_detailed_threshold",
                )
            )
        if (
            policy["item_evidence_summary_threshold"]
            > policy["item_evidence_detailed_threshold"]
        ):
            issues.append(
                ConfigBundleSemanticIssue(
                    "POLICY_THRESHOLD_ORDER_INVALID",
                    "item evidence summary threshold exceeds detailed threshold",
                )
            )

        limits = config["limits"]
        default_limit = limits["default_final_items"]
        maximum_limit = limits["max_final_items"]
        hydration_limit = limits["hydration_candidate_limit"]
        if default_limit > maximum_limit:
            issues.append(
                ConfigBundleSemanticIssue(
                    "DEFAULT_LIMIT_EXCEEDS_MAX",
                    "default limit exceeds maximum",
                )
            )
        if maximum_limit > 20:
            issues.append(
                ConfigBundleSemanticIssue(
                    "MAX_LIMIT_EXCEEDS_PROTOCOL",
                    "maximum must not exceed 20",
                )
            )
        if hydration_limit < maximum_limit:
            issues.append(
                ConfigBundleSemanticIssue(
                    "HYDRATION_LIMIT_TOO_SMALL",
                    "hydration limit is below maximum output",
                )
            )
        for output_type, minimum in limits["min_items_by_output"].items():
            if minimum > maximum_limit:
                issues.append(
                    ConfigBundleSemanticIssue(
                        "OUTPUT_MINIMUM_EXCEEDS_MAX",
                        f"{output_type} minimum exceeds maximum output",
                    )
                )

        for event_type, rule in config["behavior"].items():
            score = rule["score"]
            half_life = rule["half_life_days"]
            if score == 0 and half_life is not None:
                issues.append(
                    ConfigBundleSemanticIssue(
                        "ZERO_SCORE_HALF_LIFE_INVALID",
                        f"behavior.{event_type} must use null half_life_days",
                    )
                )
            if score != 0 and (
                not isinstance(half_life, (int, float)) or half_life <= 0
            ):
                issues.append(
                    ConfigBundleSemanticIssue(
                        "ACTIVE_SCORE_HALF_LIFE_INVALID",
                        f"behavior.{event_type} must use a positive half_life_days",
                    )
                )

        penalties = config["penalties"]
        if penalties["exposure_step"] > penalties["exposure_max"]:
            issues.append(
                ConfigBundleSemanticIssue(
                    "PENALTY_STEP_EXCEEDS_MAX",
                    "penalties.exposure_step exceeds exposure_max",
                )
            )
        popularity_weights = (
            config["popularity"]["click_weight"],
            config["popularity"]["favorite_weight"],
            config["popularity"]["borrow_weight"],
        )
        if not any(weight > 0 for weight in popularity_weights):
            issues.append(
                ConfigBundleSemanticIssue(
                    "POPULARITY_WEIGHTS_ALL_ZERO",
                    "at least one popularity weight must be positive",
                )
            )
    except (KeyError, TypeError, ValueError) as exc:
        issues.append(
            ConfigBundleSemanticIssue(
                "CONFIG_SEMANTIC_FIELD_MISSING",
                str(exc),
            )
        )
    return tuple(issues)
