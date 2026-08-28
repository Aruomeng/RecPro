from __future__ import annotations

import unittest
from uuid import uuid4

from backend.app.api.errors import PublicAPIError
from backend.app.api.recommendation import (
    RecommendationTaskCreateRequest,
    _validate_request_shape,
    build_recommendation_command,
)
from backend.app.api.recommendation_runs import (
    build_recommendation_command as asynchronous_command_builder,
)
from backend.app.shared_kernel.contracts.auth import AuthenticatedPrincipal


def request(*, constraints: dict[str, object] | None = None) -> RecommendationTaskCreateRequest:
    return RecommendationTaskCreateRequest(
        request_id=uuid4(),
        session_id=uuid4(),
        scene="SEARCH_AFTER",
        input_text="多智能体推荐系统",
        constraints=constraints or {},
    )


class RecommendationAuthorizationBoundaryTests(unittest.TestCase):
    def test_sync_and_async_routes_share_the_same_trusted_builder(self) -> None:
        self.assertIs(build_recommendation_command, asynchronous_command_builder)

    def test_formal_principal_without_consent_cannot_enable_profile_access(self) -> None:
        principal = AuthenticatedPrincipal(
            user_id=10_000,
            session_id=uuid4(),
            roles=frozenset({"user"}),
        )
        command = build_recommendation_command(
            request(constraints={"availability": "AVAILABLE_BORROW"}),
            principal=principal,
            app_env="demo",
        )

        self.assertFalse(command.constraints["_personalization_enabled"])
        self.assertTrue(command.constraints["profile_empty"])
        self.assertEqual("AVAILABLE_BORROW", command.constraints["availability"])

    def test_consent_derived_permission_enables_profile_access(self) -> None:
        principal = AuthenticatedPrincipal(
            user_id=10_000,
            session_id=uuid4(),
            roles=frozenset({"user"}),
            permissions=frozenset({"personalization.profile.use"}),
        )
        command = build_recommendation_command(
            request(), principal=principal, app_env="demo"
        )

        self.assertTrue(command.constraints["_personalization_enabled"])
        self.assertFalse(command.constraints["profile_empty"])

    def test_all_server_owned_constraint_fields_are_rejected(self) -> None:
        for field in (
            "_personalization_enabled",
            "profile_empty",
            "profile_version",
            "user_id",
        ):
            with self.subTest(field=field), self.assertRaises(PublicAPIError) as caught:
                _validate_request_shape(request(constraints={field: True}))
            self.assertEqual(422, caught.exception.status_code)
            self.assertEqual("UNKNOWN_FIELD", caught.exception.code.value)
            self.assertEqual([field], caught.exception.details["fields"])


if __name__ == "__main__":
    unittest.main()
