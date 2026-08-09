"""Evidence-only template explanations with no LLM dependency."""

from __future__ import annotations

from backend.app.recommendation.domain.public import CandidateFeature, IntentResult


def render_explanation(feature: CandidateFeature, intent: IntentResult) -> tuple[str, tuple[dict[str, object], ...]]:
    topic = ", ".join(intent.topic_terms) if intent.topic_terms else "当前主题"
    channel = feature.primary_channel.lower()
    if feature.negative_penalty > 0:
        text = f"该资源与{topic}相关，但存在主题负偏好惩罚，因此排序位置有所降低。"
    elif channel == "PROFILE":
        text = f"该资源与{topic}相关，并匹配你的历史兴趣画像。"
    elif channel == "KEYWORD":
        text = f"该资源与{topic}的标题、摘要或关键词有明确匹配。"
    else:
        text = f"该资源属于{topic}主题，并在当前目录中保持可用。"
    refs = (
        {"type": "RESOURCE_CATALOG", "resource_id": feature.resource.id},
        {"type": "RECALL_CHANNEL", "channel": feature.primary_channel},
    )
    return text, refs
