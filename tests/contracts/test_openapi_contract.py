from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[2]
OPENAPI_PATH = ROOT / "contracts/openapi/openapi-v1.json"
API_DOCUMENT_PATH = ROOT / "docs/api.md"
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}

COMMON_RESPONSE_HEADERS = {"X-Request-Id", "X-Trace-Id"}
IDEMPOTENCY_RESPONSE_HEADER = "Idempotency-Replayed"
ERROR_SCHEMA_REF = "#/components/schemas/ErrorResponse"

USER_SCOPED_OPERATION_IDS = {
    "recommendation_create_task_v1",
    "recommendation_submit_clarification_v1",
    "recommendation_get_task_v1",
    "recommendation_get_record_v1",
    "recommendation_get_item_explanation_v1",
    "interaction_append_impressions_v1",
    "interaction_append_feedback_v1",
    "interaction_append_behavior_event_v1",
    "profile_get_snapshot_v1",
    "profile_refresh_v1",
}

READ_ERROR_STATUSES = {"401", "403", "404", "422", "429", "503", "504"}
WRITE_ERROR_STATUSES = READ_ERROR_STATUSES | {"400", "409"}
EXPECTED_ERROR_STATUSES = {
    "health_liveness_v1": set(),
    "health_readiness_v1": {"503"},
    "recommendation_create_task_v1": WRITE_ERROR_STATUSES,
    "recommendation_submit_clarification_v1": WRITE_ERROR_STATUSES,
    "recommendation_get_task_v1": READ_ERROR_STATUSES,
    "recommendation_get_record_v1": READ_ERROR_STATUSES,
    "recommendation_get_item_explanation_v1": READ_ERROR_STATUSES,
    "interaction_append_impressions_v1": WRITE_ERROR_STATUSES,
    "interaction_append_feedback_v1": WRITE_ERROR_STATUSES,
    "interaction_append_behavior_event_v1": WRITE_ERROR_STATUSES,
    "profile_get_snapshot_v1": READ_ERROR_STATUSES,
    "profile_refresh_v1": WRITE_ERROR_STATUSES,
    "debug_get_task_context_v1": READ_ERROR_STATUSES,
    "debug_get_task_trace_v1": READ_ERROR_STATUSES,
    "debug_get_policy_decision_v1": READ_ERROR_STATUSES,
}


def load_openapi() -> dict[str, Any]:
    return json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))


def iter_operations(document: dict[str, Any]):
    for path, path_item in document["paths"].items():
        for method, operation in path_item.items():
            if method in HTTP_METHODS:
                yield path, method, operation


def resolve_local_ref(
    document: dict[str, Any],
    value: dict[str, Any],
) -> dict[str, Any]:
    reference = value.get("$ref")
    if reference is None:
        return value
    if not reference.startswith("#/"):
        raise AssertionError(f"Only local references are allowed here: {reference}")

    resolved: Any = document
    for token in reference[2:].split("/"):
        resolved = resolved[token.replace("~1", "/").replace("~0", "~")]
    if not isinstance(resolved, dict):
        raise AssertionError(f"Reference does not resolve to an object: {reference}")
    return resolved


class OpenApiContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.document = load_openapi()
        cls.operations = list(iter_operations(cls.document))

    def test_operation_ids_remain_unique_and_versioned(self) -> None:
        operation_ids = [operation["operationId"] for _, _, operation in self.operations]

        self.assertEqual(15, len(operation_ids))
        self.assertEqual(15, len(set(operation_ids)))
        for operation_id in operation_ids:
            self.assertRegex(
                operation_id,
                re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*_v1$"),
            )

    def test_every_operation_response_declares_trace_headers(self) -> None:
        for path, method, operation in self.operations:
            with self.subTest(path=path, method=method):
                self.assertTrue(operation.get("responses"))
                for status, response_or_ref in operation["responses"].items():
                    response = resolve_local_ref(self.document, response_or_ref)
                    headers = set(response.get("headers", {}))
                    self.assertTrue(
                        COMMON_RESPONSE_HEADERS <= headers,
                        f"{method.upper()} {path} {status} is missing trace headers",
                    )

    def test_every_operation_accepts_optional_client_request_id(self) -> None:
        expected_ref = "#/components/parameters/ClientRequestId"
        parameter = self.document["components"]["parameters"]["ClientRequestId"]
        self.assertEqual("X-Request-Id", parameter["name"])
        self.assertEqual("header", parameter["in"])
        self.assertFalse(parameter["required"])
        self.assertEqual("uuid", parameter["schema"]["format"])

        for path, method, operation in self.operations:
            with self.subTest(path=path, method=method):
                refs = {
                    item.get("$ref")
                    for item in operation.get("parameters", [])
                    if isinstance(item, dict)
                }
                self.assertIn(expected_ref, refs)

    def test_every_post_is_idempotent_and_declares_conflict(self) -> None:
        post_count = 0
        for path, method, operation in self.operations:
            if method != "post":
                continue
            post_count += 1
            parameter_refs = {
                parameter.get("$ref")
                for parameter in operation.get("parameters", [])
                if isinstance(parameter, dict)
            }

            with self.subTest(path=path):
                self.assertIn(
                    "#/components/parameters/IdempotencyKey",
                    parameter_refs,
                )
                self.assertIn("409", operation["responses"])
                for status, response_or_ref in operation["responses"].items():
                    response = resolve_local_ref(self.document, response_or_ref)
                    self.assertIn(
                        IDEMPOTENCY_RESPONSE_HEADER,
                        response.get("headers", {}),
                        f"POST {path} {status} lacks replay disclosure",
                    )

        self.assertEqual(6, post_count)

    def test_non_success_responses_use_the_common_error_schema(self) -> None:
        allowed_error_statuses = {
            "400",
            "401",
            "403",
            "404",
            "409",
            "422",
            "429",
            "503",
            "504",
        }

        for path, method, operation in self.operations:
            for status, response_or_ref in operation["responses"].items():
                if status.startswith("2"):
                    continue
                with self.subTest(path=path, method=method, status=status):
                    self.assertIn(status, allowed_error_statuses)
                    response = resolve_local_ref(self.document, response_or_ref)
                    schema = response["content"]["application/json"]["schema"]
                    self.assertEqual({"$ref": ERROR_SCHEMA_REF}, schema)

    def test_each_operation_has_the_frozen_error_status_coverage(self) -> None:
        found_operation_ids = set()

        for path, method, operation in self.operations:
            operation_id = operation["operationId"]
            found_operation_ids.add(operation_id)
            actual_error_statuses = {
                status
                for status in operation["responses"]
                if not status.startswith("2")
            }
            with self.subTest(path=path, method=method):
                self.assertEqual(
                    EXPECTED_ERROR_STATUSES[operation_id],
                    actual_error_statuses,
                )

        self.assertEqual(set(EXPECTED_ERROR_STATUSES), found_operation_ids)

    def test_demo_identity_is_limited_to_user_scoped_routes(self) -> None:
        for path, method, operation in self.operations:
            operation_id = operation["operationId"]
            parameter_refs = {
                parameter.get("$ref")
                for parameter in operation.get("parameters", [])
                if isinstance(parameter, dict)
            }
            security = operation.get("security", self.document.get("security", []))
            security_schemes = {
                scheme
                for alternative in security
                for scheme in alternative
            }

            with self.subTest(path=path, method=method):
                if operation_id in USER_SCOPED_OPERATION_IDS:
                    self.assertIn(
                        "#/components/parameters/DemoUserId",
                        parameter_refs,
                    )
                    self.assertIn("demoUserAuth", security_schemes)
                else:
                    self.assertNotIn(
                        "#/components/parameters/DemoUserId",
                        parameter_refs,
                    )
                    self.assertNotIn("demoUserAuth", security_schemes)

        demo_description = self.document["components"]["parameters"]["DemoUserId"][
            "description"
        ]
        self.assertIn("APP_ENV=demo", demo_description)
        self.assertIn("never grants research_admin", demo_description)

    def test_version_bundle_requires_reproducibility_versions(self) -> None:
        version_bundle = self.document["components"]["schemas"]["VersionBundle"]
        required = set(version_bundle["required"])
        expected = {
            "config_bundle",
            "policy",
            "ranking",
            "behavior_formula",
            "dataset",
        }

        self.assertTrue(expected <= required)
        self.assertTrue(expected <= set(version_bundle["properties"]))
        for property_name in expected:
            self.assertEqual(
                1,
                version_bundle["properties"][property_name]["minLength"],
            )

    def test_documented_debug_trace_matches_debug_document_schema(self) -> None:
        text = API_DOCUMENT_PATH.read_text(encoding="utf-8")
        section_start = text.index("### 11.2 `GET /debug/tasks/{task_id}/trace`")
        section = text[section_start:]
        match = re.search(r"```json\s*\n(?P<body>.*?)\n```", section, re.DOTALL)
        self.assertIsNotNone(match)
        example = json.loads(match.group("body"))
        schema = self.document["components"]["schemas"]["DebugDocument"]
        errors = list(
            Draft202012Validator(
                schema,
                format_checker=FormatChecker(),
            ).iter_errors(example)
        )
        self.assertEqual([], errors)


if __name__ == "__main__":
    unittest.main()
