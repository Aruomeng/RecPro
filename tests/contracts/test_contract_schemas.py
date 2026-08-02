from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from scripts.validate_contracts import (
    validate_config_bundle,
    validate_openapi,
    validate_repository,
)


ROOT = Path(__file__).resolve().parents[2]


class RepositoryContractTest(unittest.TestCase):
    def test_all_machine_contracts_are_consistent(self) -> None:
        issues, parsed_documents = validate_repository(ROOT)
        self.assertGreaterEqual(parsed_documents, 6)
        self.assertEqual([], issues)

    def test_weight_drift_is_rejected(self) -> None:
        config_path = ROOT / "contracts/config/examples/rec-1.0.0.json"
        schema_path = ROOT / "contracts/config/rec-config.schema.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        invalid = deepcopy(config)
        invalid["ranking"]["book"]["profile_score"] = 0.5
        codes = {issue.code for issue in validate_config_bundle(invalid, schema)}
        self.assertIn("WEIGHT_SUM_INVALID", codes)

    def test_nonzero_behavior_requires_half_life(self) -> None:
        config_path = ROOT / "contracts/config/examples/rec-1.0.0.json"
        schema_path = ROOT / "contracts/config/rec-config.schema.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        invalid = deepcopy(config)
        invalid["behavior"]["SEARCH"]["half_life_days"] = None
        codes = {issue.code for issue in validate_config_bundle(invalid, schema)}
        self.assertIn("ACTIVE_SCORE_HALF_LIFE_INVALID", codes)

    def test_misspelled_policy_field_is_rejected(self) -> None:
        config_path = ROOT / "contracts/config/examples/rec-1.0.0.json"
        schema_path = ROOT / "contracts/config/rec-config.schema.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        invalid = deepcopy(config)
        invalid["policy"]["profile_guided_thresold"] = invalid["policy"].pop(
            "profile_guided_threshold"
        )
        codes = {issue.code for issue in validate_config_bundle(invalid, schema)}
        self.assertIn("CONFIG_SCHEMA_VIOLATION", codes)

    def test_reversed_policy_thresholds_are_rejected(self) -> None:
        config_path = ROOT / "contracts/config/examples/rec-1.0.0.json"
        schema_path = ROOT / "contracts/config/rec-config.schema.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        invalid = deepcopy(config)
        invalid["policy"]["evidence_degraded_threshold"] = 0.9
        invalid["policy"]["evidence_detailed_threshold"] = 0.3
        codes = {issue.code for issue in validate_config_bundle(invalid, schema)}
        self.assertIn("POLICY_THRESHOLD_ORDER_INVALID", codes)

    def test_negative_freshness_is_rejected(self) -> None:
        config_path = ROOT / "contracts/config/examples/rec-1.0.0.json"
        schema_path = ROOT / "contracts/config/rec-config.schema.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        invalid = deepcopy(config)
        invalid["freshness"]["book_half_life_days"] = -1
        codes = {issue.code for issue in validate_config_bundle(invalid, schema)}
        self.assertIn("CONFIG_SCHEMA_VIOLATION", codes)

    def test_non_finite_numbers_are_rejected_by_shared_semantics(self) -> None:
        config_path = ROOT / "contracts/config/examples/rec-1.0.0.json"
        schema_path = ROOT / "contracts/config/rec-config.schema.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        invalid = deepcopy(config)
        invalid["probe"]["metadata_min"] = float("nan")

        codes = {issue.code for issue in validate_config_bundle(invalid, schema)}

        self.assertIn("CONFIG_NON_FINITE_NUMBER", codes)

    def test_penalty_wrong_type_is_rejected(self) -> None:
        config_path = ROOT / "contracts/config/examples/rec-1.0.0.json"
        schema_path = ROOT / "contracts/config/rec-config.schema.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        invalid = deepcopy(config)
        invalid["penalties"]["exposure_step"] = "0.1"
        codes = {issue.code for issue in validate_config_bundle(invalid, schema)}
        self.assertIn("CONFIG_SCHEMA_VIOLATION", codes)

    def test_unknown_popularity_normalization_is_rejected(self) -> None:
        config_path = ROOT / "contracts/config/examples/rec-1.0.0.json"
        schema_path = ROOT / "contracts/config/rec-config.schema.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        invalid = deepcopy(config)
        invalid["popularity"]["normalization"] = "MIN_MAX"
        codes = {issue.code for issue in validate_config_bundle(invalid, schema)}
        self.assertIn("CONFIG_SCHEMA_VIOLATION", codes)

    def test_openapi_rejects_destructive_http_method(self) -> None:
        openapi_path = ROOT / "contracts/openapi/openapi-v1.json"
        document = json.loads(openapi_path.read_text(encoding="utf-8"))
        invalid = deepcopy(document)
        invalid["paths"]["/api/v1/resources/{resource_id}"] = {
            "delete": {"operationId": "purgeResource", "responses": {"204": {}}}
        }
        codes = {
            issue.code
            for issue in validate_openapi(
                invalid,
                "contracts/openapi/openapi-v1.json",
            )
        }
        self.assertIn("OPENAPI_DESTRUCTIVE_METHOD_FORBIDDEN", codes)

    def test_openapi_rejects_destructive_action_disguised_as_post(self) -> None:
        openapi_path = ROOT / "contracts/openapi/openapi-v1.json"
        document = json.loads(openapi_path.read_text(encoding="utf-8"))
        for route, operation_id in (
            ("/api/v1/profiles/{user_id}/purge", "profile_purge_v1"),
            ("/api/v1/profiles/{user_id}/reset", "profile_reset_v1"),
            ("/api/v1/admin/purgeAll", "admin_purgeall_v1"),
        ):
            with self.subTest(route=route):
                invalid = deepcopy(document)
                invalid["paths"][route] = {
                    "post": {
                        "operationId": operation_id,
                        "parameters": [
                            {"$ref": "#/components/parameters/IdempotencyKey"}
                        ],
                        "responses": {"202": {}, "409": {}},
                    }
                }
                codes = {
                    issue.code
                    for issue in validate_openapi(
                        invalid,
                        "contracts/openapi/openapi-v1.json",
                    )
                }
                self.assertIn("OPENAPI_DESTRUCTIVE_ACTION_FORBIDDEN", codes)

    def test_openapi_write_requires_conflict_response(self) -> None:
        openapi_path = ROOT / "contracts/openapi/openapi-v1.json"
        document = json.loads(openapi_path.read_text(encoding="utf-8"))
        invalid = deepcopy(document)
        invalid["paths"]["/api/v1/recommendation-tasks"]["post"]["responses"].pop(
            "409",
            None,
        )
        codes = {
            issue.code
            for issue in validate_openapi(
                invalid,
                "contracts/openapi/openapi-v1.json",
            )
        }
        self.assertIn("OPENAPI_WRITE_CONFLICT_RESPONSE_MISSING", codes)

    def test_openapi_operation_requires_client_request_id_header(self) -> None:
        openapi_path = ROOT / "contracts/openapi/openapi-v1.json"
        document = json.loads(openapi_path.read_text(encoding="utf-8"))
        invalid = deepcopy(document)
        invalid["paths"]["/api/v1/health/live"]["get"]["parameters"] = []
        codes = {
            issue.code
            for issue in validate_openapi(
                invalid,
                "contracts/openapi/openapi-v1.json",
            )
        }
        self.assertIn("OPENAPI_CLIENT_REQUEST_ID_HEADER_MISSING", codes)


if __name__ == "__main__":
    unittest.main()
