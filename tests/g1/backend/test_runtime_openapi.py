from __future__ import annotations

import unittest

from backend.app.config import AppSettings
from backend.app.main import create_app
from backend.app.observability.domain import ComponentReadiness, ComponentStatus


class UpProbe:
    async def check(self) -> ComponentReadiness:
        return ComponentReadiness(ComponentStatus.UP, required=True)


class RuntimeOpenAPIContractTest(unittest.TestCase):
    def setUp(self) -> None:
        settings = AppSettings(
            app_env="test",
            mysql_password="isolated-test-password",
        )
        self.document = create_app(
            settings=settings,
            readiness_probe=UpProbe(),
            config_bundle_probe=UpProbe(),
        ).openapi()

    def test_health_operations_and_request_id_parameter_match_contract(self) -> None:
        expected_operation_ids = {
            "/api/v1/health/live": "health_liveness_v1",
            "/api/v1/health/ready": "health_readiness_v1",
        }
        for path, operation_id in expected_operation_ids.items():
            with self.subTest(path=path):
                operation = self.document["paths"][path]["get"]
                self.assertEqual(operation_id, operation["operationId"])
                parameters = [
                    item
                    for item in operation["parameters"]
                    if item["name"] == "X-Request-Id" and item["in"] == "header"
                ]
                self.assertEqual(1, len(parameters))
                self.assertFalse(parameters[0]["required"])
                self.assertEqual(
                    {"type": "string", "format": "uuid"},
                    parameters[0]["schema"],
                )

    def test_success_and_failure_responses_declare_correlation_headers(self) -> None:
        response_locations = (
            ("/api/v1/health/live", "200"),
            ("/api/v1/health/ready", "200"),
            ("/api/v1/health/ready", "503"),
        )
        for path, status in response_locations:
            with self.subTest(path=path, status=status):
                headers = self.document["paths"][path]["get"]["responses"][status][
                    "headers"
                ]
                self.assertEqual({"X-Request-Id", "X-Trace-Id"}, set(headers))
                for header in headers.values():
                    self.assertEqual("uuid", header["schema"]["format"])

    def test_ready_503_references_uniform_error_response_schema(self) -> None:
        schema = self.document["paths"]["/api/v1/health/ready"]["get"][
            "responses"
        ]["503"]["content"]["application/json"]["schema"]
        self.assertEqual(
            "#/components/schemas/ErrorResponse",
            schema["$ref"],
        )

    def test_health_response_required_and_optional_fields_match_frozen_shapes(self) -> None:
        schemas = self.document["components"]["schemas"]
        self.assertEqual(
            {"status", "service", "version", "time"},
            set(schemas["LivenessResponse"]["required"]),
        )
        self.assertEqual(
            {
                "status",
                "can_recommend",
                "components",
                "config_bundle_version",
                "checked_at",
            },
            set(schemas["ReadinessResponse"]["required"]),
        )
        component = schemas["ComponentReadinessResponse"]
        self.assertEqual({"status", "required"}, set(component["required"]))
        for field_name in ("active_version", "provider", "error_code"):
            self.assertEqual("string", component["properties"][field_name]["type"])
