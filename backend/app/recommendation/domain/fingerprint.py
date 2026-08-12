"""Content-addressed recommendation output fingerprints."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from math import isfinite
from typing import Any


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def execution_fingerprint(
    execution: Any,
    *,
    config_bundle_version: str,
    dataset_version: str,
    seed: str,
    evaluation_at: datetime,
) -> str:
    """Hash fixed versions, time, and every ranked output field.

    The function is pure and intentionally accepts the domain execution value
    without importing an adapter or persistence model.  It is suitable for
    evaluation artifacts and replay comparisons.
    """

    for name, value in (
        ("config_bundle_version", config_bundle_version),
        ("dataset_version", dataset_version),
        ("seed", seed),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must not be blank")
    if not isinstance(evaluation_at, datetime):
        raise ValueError("evaluation_at must be a datetime")
    items: list[dict[str, object]] = []
    for item in execution.items:
        feature = item.feature
        numeric_values = (
            feature.rrf_score,
            feature.final_score,
            feature.negative_penalty,
            feature.evidence_confidence,
        )
        if not all(isfinite(float(value)) for value in numeric_values):
            raise ValueError("execution contains a non-finite score")
        items.append(
            {
                "rank_no": item.rank_no,
                "resource_id": feature.resource.id,
                "channel_ranks": dict(sorted(feature.channel_ranks.items())),
                "channel_scores": dict(sorted(feature.channel_scores.items())),
                "rrf_score": feature.rrf_score,
                "final_score": feature.final_score,
                "negative_penalty": feature.negative_penalty,
                "evidence_confidence": feature.evidence_confidence,
                "primary_channel": feature.primary_channel,
                "diversity_relaxed": feature.diversity_relaxed,
                "explanation": item.explanation,
                "evidence_refs": list(item.evidence_refs),
            }
        )
    document = {
        "schema_version": "recommendation-fingerprint-v1",
        "config_bundle_version": config_bundle_version,
        "dataset_version": dataset_version,
        "seed": seed,
        "evaluation_at": evaluation_at.isoformat(),
        "intent": {
            "intent_type": execution.intent.intent_type,
            "confidence": execution.intent.confidence,
            "topic_terms": list(execution.intent.topic_terms),
            "resource_types": list(execution.intent.resource_types),
            "reason_codes": list(execution.intent.reason_codes),
        },
        "items": items,
        "warnings": list(execution.warnings),
        "decision_reason_codes": list(execution.decision_reason_codes),
    }
    return hashlib.sha256(_canonical(document)).hexdigest()


__all__ = ["execution_fingerprint"]
