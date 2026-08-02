from __future__ import annotations

import unittest
from uuid import UUID, uuid4
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.config import AppSettings, ConfigurationState
from backend.app.main import create_app
from backend.app.observability.domain import ComponentReadiness, ComponentStatus
from backend.app.shared_kernel.contracts.errors import ErrorCode


class FakeProbe:
    def __init__(self, result: ComponentReadiness) -> None:
        self.result = result
        self.calls = 0

    async def check(self) -> ComponentReadiness:
        self.calls += 1
        return self.result


def test_settings() -> AppSettings:
    return AppSettings(
        app_env="test",
        mysql_password="isolated-test-password",
    )


class HealthAPITest(unittest.TestCase):
    def test_liveness_is_process_only_and_echoes_request_id(self) -> None:
        probe = FakeProbe(ComponentReadiness(ComponentStatus.DOWN, required=True))
        client_request_id = uuid4()
        with TestClient(create_app(settings=test_settings(), readiness_probe=probe)) as client:
            response = client.get(
                "/api/v1/health/live",
                headers={"X-Request-Id": str(client_request_id)},
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual(0, probe.calls)
        self.assertEqual(str(client_request_id), response.headers["X-Request-Id"])
        UUID(response.headers["X-Trace-Id"])
        self.assertEqual(
            {"status", "service", "version", "time"}, set(response.json())
        )
        self.assertEqual("UP", response.json()["status"])

    def test_ready_is_truthfully_degraded_when_mysql_is_safe(self) -> None:
        probe = FakeProbe(ComponentReadiness(ComponentStatus.UP, required=True))
        with TestClient(create_app(settings=test_settings(), readiness_probe=probe)) as client:
            response = client.get("/api/v1/health/ready")

        self.assertEqual(200, response.status_code)
        body = response.json()
        self.assertEqual("DEGRADED", body["status"])
        self.assertFalse(body["can_recommend"])
        self.assertEqual("UP", body["components"]["mysql"]["status"])
        self.assertEqual(
            "DISABLED", body["components"]["recommendation_pipeline"]["status"]
        )
        self.assertEqual(
            "G1_NOT_IMPLEMENTED",
            body["components"]["recommendation_pipeline"]["error_code"],
        )
        self.assertEqual("MOCK", body["components"]["llm"]["status"])
        self.assertNotIn("active_version", body["components"]["mysql"])

    def test_unavailable_mysql_uses_uniform_error_response(self) -> None:
        probe = FakeProbe(
            ComponentReadiness(
                ComponentStatus.DOWN,
                required=True,
                error_code=ErrorCode.CORE_STORAGE_UNAVAILABLE.value,
            )
        )
        with TestClient(create_app(settings=test_settings(), readiness_probe=probe)) as client:
            response = client.get("/api/v1/health/ready")

        self.assertEqual(503, response.status_code)
        body = response.json()
        self.assertEqual(
            ErrorCode.CORE_STORAGE_UNAVAILABLE.value, body["error"]["code"]
        )
        self.assertTrue(body["error"]["retryable"])
        self.assertEqual({"component": "mysql"}, body["error"]["details"])
        UUID(body["request_id"])
        UUID(body["trace_id"])
        self.assertNotIn("password", response.text.casefold())
        self.assertNotIn("dsn", response.text.casefold())

    def test_unsafe_grants_fail_closed_and_are_not_retryable(self) -> None:
        probe = FakeProbe(
            ComponentReadiness(
                ComponentStatus.DOWN,
                required=True,
                error_code=ErrorCode.UNSAFE_DATABASE_PRIVILEGES.value,
            )
        )
        with TestClient(create_app(settings=test_settings(), readiness_probe=probe)) as client:
            response = client.get("/api/v1/health/ready")

        self.assertEqual(503, response.status_code)
        self.assertEqual(
            ErrorCode.UNSAFE_DATABASE_PRIVILEGES.value,
            response.json()["error"]["code"],
        )
        self.assertFalse(response.json()["error"]["retryable"])

    def test_invalid_configuration_does_not_call_probe(self) -> None:
        probe = FakeProbe(ComponentReadiness(ComponentStatus.UP, required=True))
        state = ConfigurationState(
            settings=test_settings(),
            is_valid=False,
            error_code=ErrorCode.CONFIG_BUNDLE_INVALID.value,
        )
        with TestClient(
            create_app(configuration_state=state, readiness_probe=probe)
        ) as client:
            response = client.get("/api/v1/health/ready")

        self.assertEqual(503, response.status_code)
        self.assertEqual(0, probe.calls)
        self.assertEqual(
            ErrorCode.CONFIG_BUNDLE_INVALID.value,
            response.json()["error"]["code"],
        )
        self.assertEqual(
            {"component": "configuration"}, response.json()["error"]["details"]
        )

    def test_invalid_bundle_fails_before_mysql_probe(self) -> None:
        mysql_probe = FakeProbe(ComponentReadiness(ComponentStatus.UP, required=True))
        bundle_probe = FakeProbe(
            ComponentReadiness(
                ComponentStatus.DOWN,
                required=True,
                error_code=ErrorCode.CONFIG_BUNDLE_INVALID.value,
            )
        )
        with TestClient(
            create_app(
                settings=test_settings(),
                readiness_probe=mysql_probe,
                config_bundle_probe=bundle_probe,
            )
        ) as client:
            response = client.get("/api/v1/health/ready")

        self.assertEqual(503, response.status_code)
        self.assertEqual(1, bundle_probe.calls)
        self.assertEqual(0, mysql_probe.calls)
        self.assertEqual(
            ErrorCode.CONFIG_BUNDLE_INVALID.value,
            response.json()["error"]["code"],
        )

    def test_invalid_request_id_is_replaced_without_adding_an_undeclared_422(self) -> None:
        probe = FakeProbe(ComponentReadiness(ComponentStatus.UP, required=True))
        with TestClient(create_app(settings=test_settings(), readiness_probe=probe)) as client:
            response = client.get(
                "/api/v1/health/live", headers={"X-Request-Id": "not-a-uuid"}
            )

        self.assertEqual(200, response.status_code)
        UUID(response.headers["X-Request-Id"])
        self.assertNotEqual("not-a-uuid", response.headers["X-Request-Id"])
        self.assertEqual(0, probe.calls)

    def test_unexpected_error_never_logs_arbitrary_exception_text(self) -> None:
        probe = FakeProbe(ComponentReadiness(ComponentStatus.UP, required=True))
        application = create_app(settings=test_settings(), readiness_probe=probe)

        @application.get("/api/v1/synthetic-failure")
        async def synthetic_failure() -> None:
            raise RuntimeError("SYNTHETIC_SENSITIVE_MARKER")

        with patch("backend.app.api.errors.logger.error") as log_error, TestClient(
            application,
            raise_server_exceptions=False,
        ) as client:
            response = client.get("/api/v1/synthetic-failure")

        self.assertEqual(503, response.status_code)
        self.assertNotIn("SYNTHETIC_SENSITIVE_MARKER", response.text)
        log_error.assert_called_once_with(
            "unhandled_request_error",
            error_type="RuntimeError",
        )

    def test_unknown_route_uses_uniform_error_response(self) -> None:
        probe = FakeProbe(ComponentReadiness(ComponentStatus.UP, required=True))
        with TestClient(create_app(settings=test_settings(), readiness_probe=probe)) as client:
            response = client.get("/api/v1/not-present")

        self.assertEqual(404, response.status_code)
        self.assertEqual(ErrorCode.NOT_FOUND.value, response.json()["error"]["code"])
