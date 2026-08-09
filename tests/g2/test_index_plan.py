from __future__ import annotations

import unittest
from datetime import datetime

from backend.app.catalog.application.public import plan_index_builds
from backend.app.catalog.domain.models import ResourceSummary


def resource(resource_id: int, title: str) -> ResourceSummary:
    return ResourceSummary(
        id=resource_id,
        resource_type="BOOK",
        external_id=f"resource-{resource_id}",
        title=title,
        authors=("Author",),
        abstract_text="Abstract",
        keywords=("智慧图书馆",),
        category_code="G25",
        publication_year=2025,
        availability_status="AVAILABLE_BORROW",
        available_from=datetime(2025, 1, 1),
        access_url=None,
        metadata_quality=0.9,
        is_classic=False,
        metadata_version=1,
        language="zh-CN",
        difficulty_level=2,
    )


class G2IndexPlanTests(unittest.TestCase):
    def test_plan_is_two_targets_per_resource_and_deterministic(self) -> None:
        resources = (resource(1, "A"), resource(2, "B"))
        first = plan_index_builds(resources)
        second = plan_index_builds(resources)
        self.assertEqual(first, second)
        self.assertEqual(4, len(first))
        self.assertEqual({"VECTOR", "GRAPH"}, {item.target for item in first})
        self.assertEqual({"recpro_vector_g2_index_v1", "recpro_graph_g2_index_v1"}, {item.namespace_name for item in first})
        self.assertTrue(all(item.status == "PLANNED" for item in first))

    def test_unsafe_version_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            plan_index_builds((resource(1, "A"),), index_version="g2/index")


if __name__ == "__main__":
    unittest.main()
