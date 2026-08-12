from __future__ import annotations

from math import isfinite
import unittest
from datetime import datetime

from backend.app.catalog.domain.public import ResourceSummary, ResourceTagEvidence
from backend.app.recommendation.application.intent import classify_intent
from backend.app.recommendation.application.public import execute_recommendation
from backend.app.recommendation.domain.fingerprint import execution_fingerprint
from backend.app.recommendation.domain.public import ProfileSignal, RecommendationRequest


def resource(resource_id: int, title: str, *, author: str = "A") -> ResourceSummary:
    return ResourceSummary(
        id=resource_id,
        resource_type="BOOK" if resource_id % 2 else "PAPER",
        external_id=f"resource-{resource_id}",
        title=title,
        authors=(author,),
        abstract_text=f"{title} 摘要",
        keywords=(title,),
        category_code="G25",
        publication_year=2025,
        availability_status="AVAILABLE_BORROW" if resource_id % 2 else "AVAILABLE_ONLINE",
        available_from=datetime(2024, 1, 1),
        access_url=None,
        metadata_quality=0.9,
        is_classic=False,
        metadata_version=1,
        language="zh-CN",
        difficulty_level=2,
    )


class G3RecommendationServiceTests(unittest.TestCase):
    def test_intent_preserves_explicit_topic_and_type(self) -> None:
        result = classify_intent("我要看多智能体论文", requested_resource_types=("PAPER",))
        self.assertEqual("PAPER_RECOMMENDATION", result.intent_type)
        self.assertIn("multi-agent", result.topic_terms)
        self.assertGreaterEqual(result.confidence, 0.9)

    def test_recommendation_is_deterministic_and_has_evidence(self) -> None:
        resources = tuple(resource(index, "多智能体" if index < 4 else "智慧图书馆") for index in range(1, 7))
        tags = tuple(
            ResourceTagEvidence(item.id, 1, "multi-agent", 0.9, 0.9, "IMPORT")
            for item in resources
        )
        request = RecommendationRequest(
            user_id=1001,
            input_text="多智能体推荐系统",
            resource_types=("BOOK", "PAPER"),
            limit=5,
            evaluation_at=datetime(2026, 1, 1),
        )
        first = execute_recommendation(
            request,
            resources=resources,
            tags=tags,
            profile_signals=(ProfileSignal(1, 0.8),),
            behavior_events=((1, "FAVORITE_RESOURCE"),),
        )
        second = execute_recommendation(
            request,
            resources=tuple(reversed(resources)),
            tags=tuple(reversed(tags)),
            profile_signals=(ProfileSignal(1, 0.8),),
            behavior_events=((1, "FAVORITE_RESOURCE"),),
        )
        self.assertEqual(first, second)
        self.assertEqual(5, len(first.items))
        self.assertTrue(all(item.feature.evidence_confidence >= 0 for item in first.items))
        self.assertTrue(all(item.evidence_refs for item in first.items))
        self.assertIn("RRF_RANKING_MMR", {step["name"] for step in first.trace_steps})

    def test_fixed_snapshot_versions_seed_and_time_have_stable_fingerprint(self) -> None:
        resources = tuple(resource(index, "多智能体" if index < 4 else "智慧图书馆") for index in range(1, 7))
        tags = tuple(
            ResourceTagEvidence(item.id, 1, "multi-agent", 0.9, 0.9, "IMPORT")
            for item in resources
        )
        request = RecommendationRequest(
            user_id=1001,
            input_text="多智能体推荐系统",
            resource_types=("BOOK", "PAPER"),
            limit=5,
            evaluation_at=datetime(2026, 1, 1),
        )
        first = execute_recommendation(
            request,
            resources=resources,
            tags=tags,
            profile_signals=(ProfileSignal(1, 0.8),),
            behavior_events=((1, "FAVORITE_RESOURCE"),),
        )
        second = execute_recommendation(
            request,
            resources=tuple(reversed(resources)),
            tags=tuple(reversed(tags)),
            profile_signals=(ProfileSignal(1, 0.8),),
            behavior_events=((1, "FAVORITE_RESOURCE"),),
        )
        metadata = {
            "config_bundle_version": "rec-1.0.0",
            "dataset_version": "lib-books-v1",
            "seed": "evaluation-seed-001",
            "evaluation_at": datetime(2026, 1, 1),
        }
        self.assertEqual(
            execution_fingerprint(first, **metadata),
            execution_fingerprint(second, **metadata),
        )

    def test_topic_negative_penalty_is_bounded_and_explanation_is_template(self) -> None:
        resources = (resource(1, "多智能体系统"), resource(2, "智慧图书馆"))
        tags = (
            ResourceTagEvidence(1, 7, "multi-agent", 1.0, 1.0, "IMPORT"),
            ResourceTagEvidence(2, 8, "digital-library", 1.0, 1.0, "IMPORT"),
        )
        result = execute_recommendation(
            RecommendationRequest(1001, "多智能体", ("BOOK", "PAPER"), 2, datetime(2026, 1, 1)),
            resources=resources,
            tags=tags,
            profile_signals=(ProfileSignal(7, 0.9), ProfileSignal(7, 0.85, negative=True)),
        )
        self.assertEqual(2, len(result.items))
        self.assertTrue(all(0 <= item.feature.final_score <= 1 for item in result.items))
        self.assertTrue(any("惩罚" in item.explanation for item in result.items))

    def test_topic_negative_counterfactual_strictly_lowers_target_score(self) -> None:
        resources = (resource(1, "多智能体系统"), resource(2, "智慧图书馆"))
        tags = (
            ResourceTagEvidence(1, 7, "multi-agent", 1.0, 1.0, "IMPORT"),
            ResourceTagEvidence(2, 8, "digital-library", 1.0, 1.0, "IMPORT"),
        )
        request = RecommendationRequest(
            1001,
            "多智能体",
            ("BOOK", "PAPER"),
            2,
            datetime(2026, 1, 1),
        )
        baseline = execute_recommendation(request, resources=resources, tags=tags)
        counterfactual = execute_recommendation(
            request,
            resources=resources,
            tags=tags,
            profile_signals=(ProfileSignal(7, 0.9, negative=True),),
        )
        baseline_target = next(item.feature for item in baseline.items if item.feature.resource.id == 1)
        counterfactual_target = next(item.feature for item in counterfactual.items if item.feature.resource.id == 1)
        self.assertGreater(counterfactual_target.negative_penalty, 0.0)
        self.assertLess(counterfactual_target.final_score, baseline_target.final_score)

    def test_limit_is_fail_closed(self) -> None:
        with self.assertRaises(ValueError):
            execute_recommendation(
                RecommendationRequest(1001, "主题", ("BOOK",), 21, datetime(2026, 1, 1)),
                resources=(),
                tags=(),
            )

    def test_missing_optional_features_keep_all_scores_finite_and_bounded(self) -> None:
        resources = (resource(1, "多智能体系统"), resource(2, "智慧图书馆"))
        imported_tags = tuple(
            ResourceTagEvidence(item.id, item.id, item.title, 0.8, 0.9, "IMPORT")
            for item in resources
        )
        cases = (
            (resources, (), (), ()),
            (resources, imported_tags, (), ()),
            (resources, (), (ProfileSignal(1, 0.8),), ((1, "VIEW_RESOURCE"),)),
            (resources, imported_tags, (ProfileSignal(1, 0.8, negative=True),), ()),
            ((), (), (), ()),
        )
        for case_no, (case_resources, case_tags, profile, behavior) in enumerate(cases, start=1):
            with self.subTest(case_no=case_no):
                result = execute_recommendation(
                    RecommendationRequest(
                        1001,
                        "多智能体",
                        ("BOOK", "PAPER"),
                        2,
                        datetime(2026, 1, 1),
                    ),
                    resources=case_resources,
                    tags=case_tags,
                    profile_signals=profile,
                    behavior_events=behavior,
                )
                for item in result.items:
                    feature = item.feature
                    for value in (
                        feature.rrf_score,
                        feature.final_score,
                        feature.negative_penalty,
                        feature.evidence_confidence,
                    ):
                        self.assertTrue(isfinite(value))
                        self.assertGreaterEqual(value, 0.0)
                        self.assertLessEqual(value, 1.0)
                    self.assertTrue(all(isfinite(score) for score in feature.channel_scores.values()))
                    self.assertTrue(item.evidence_refs)


if __name__ == "__main__":
    unittest.main()
