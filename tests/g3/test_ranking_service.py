from __future__ import annotations

from datetime import datetime
import unittest

from backend.app.catalog.domain.public import ResourceSummary, ResourceTagEvidence
from backend.app.recommendation.domain.public import CandidateFeature
from backend.app.recommendation.ranking.service import rank_candidates


def resource(resource_id: int, *, author: str, title: str) -> ResourceSummary:
    return ResourceSummary(
        id=resource_id,
        resource_type="BOOK",
        external_id=f"book-{resource_id}",
        title=title,
        authors=(author,),
        abstract_text=title,
        keywords=(title,),
        category_code="TP",
        publication_year=2025,
        availability_status="AVAILABLE_BORROW",
        available_from=datetime(2024, 1, 1),
        access_url=None,
        metadata_quality=0.9,
        is_classic=False,
        metadata_version=1,
        language="zh-CN",
        difficulty_level=2,
    )


def feature(resource_value: ResourceSummary, *, tag_id: int, score: float) -> CandidateFeature:
    return CandidateFeature(
        resource=resource_value,
        tags=(ResourceTagEvidence(resource_value.id, tag_id, "topic", 1.0, 1.0, "TEST"),),
        channel_ranks={"MYSQL": resource_value.id},
        channel_scores={"MYSQL": score},
        rrf_score=score,
        final_score=score,
        negative_penalty=0.0,
        evidence_confidence=0.9,
        primary_channel="MYSQL",
    )


class RankingDiversityTests(unittest.TestCase):
    def test_author_and_topic_caps_are_respected_when_candidates_are_sufficient(self) -> None:
        candidates = (
            feature(resource(1, author="A", title="one"), tag_id=1, score=0.9),
            feature(resource(2, author="A", title="two"), tag_id=1, score=0.8),
            feature(resource(3, author="B", title="three"), tag_id=1, score=0.7),
            feature(resource(4, author="C", title="four"), tag_id=2, score=0.6),
        )
        selected = rank_candidates(candidates, limit=3, max_same_author=1, max_same_primary_tag=2)

        self.assertEqual((1, 3, 4), tuple(item.resource.id for item in selected))
        self.assertEqual(3, len({item.resource.authors[0] for item in selected}))
        self.assertLessEqual(sum(item.tags[0].tag_id == 1 for item in selected), 2)
        self.assertFalse(any(item.diversity_relaxed for item in selected))

    def test_insufficient_candidates_mark_diversity_relaxed_instead_of_faking_diversity(self) -> None:
        candidates = (
            feature(resource(1, author="A", title="one"), tag_id=1, score=0.9),
            feature(resource(2, author="A", title="two"), tag_id=1, score=0.8),
        )
        selected = rank_candidates(candidates, limit=2, max_same_author=1, max_same_primary_tag=1)

        self.assertEqual((1, 2), tuple(item.resource.id for item in selected))
        self.assertFalse(selected[0].diversity_relaxed)
        self.assertTrue(selected[1].diversity_relaxed)


if __name__ == "__main__":
    unittest.main()
