from __future__ import annotations

import hashlib
import json
import unittest
from unittest.mock import patch

from scripts.build_formal_reader_behavior_consent_plan import (
    CONSENT_SCOPE,
    FORMAL_READER_ID,
    build_plan,
    canonical,
)
from scripts.execute_formal_reader_behavior_consent_plan import validate_plan


class FormalReaderBehaviorConsentPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.values = {
            "RECPRO_MYSQL_PORT": "62306",
            "RECPRO_MYSQL_DATABASE": "recpro",
        }
        self.counts = {
            "iam_auth_session": 10,
            "iam_refresh_token": 12,
            "iam_security_event": 19,
            "user_personalization_consent_fact": 5,
        }
        self.identity = {
            "account": {
                "user_id": FORMAL_READER_ID,
                "status": "ACTIVE",
                "auth_version": 2,
                "role_version": 1,
                "must_change_password": False,
                "account_kind": "HUMAN",
            },
            "roles": ["user"],
            "consents": {
                "BEHAVIOR_LEARNING": False,
                "DECLARED_PROFILE": True,
                "PERSONALIZED_RECOMMENDATION": True,
                "RESEARCH_ANALYTICS": True,
            },
        }

    def _build(self) -> dict[str, object]:
        with patch(
            "scripts.build_formal_reader_behavior_consent_plan.current_git_commit",
            return_value="a" * 40,
        ), patch(
            "scripts.build_formal_reader_behavior_consent_plan.require_clean_worktree",
        ):
            return build_plan(
                run_id="formal-reader-consent-test-001",
                created_at="2026-09-02T00:00:00Z",
                values=self.values,
                counts=self.counts,
                identity=self.identity,
            )

    def test_plan_is_canonical_and_has_five_append_rows(self) -> None:
        plan = self._build()
        unsigned = dict(plan)
        plan_hash = str(unsigned.pop("plan_hash"))
        self.assertEqual(plan_hash, hashlib.sha256(canonical(unsigned)).hexdigest())
        self.assertEqual(5, plan["max_changes"])
        targets = plan["targets"]
        assert isinstance(targets, list)
        self.assertEqual(
            {
                "iam_auth_session": 1,
                "iam_refresh_token": 1,
                "iam_security_event": 2,
                "user_personalization_consent_fact": 1,
            },
            {
                table: int(next(item for item in targets if f".{table}:" in item["identifier"])["expected_after_min_count"])
                - int(next(item for item in targets if f".{table}:" in item["identifier"])["expected_before_count"])
                for table in self.counts
            },
        )

    def test_executor_accepts_unchanged_plan_and_rejects_tampering(self) -> None:
        plan = self._build()
        with patch(
            "scripts.execute_formal_reader_behavior_consent_plan._load_json",
            return_value=plan,
        ), patch(
            "scripts.execute_formal_reader_behavior_consent_plan._current_commit",
            return_value="a" * 40,
        ), patch(
            "scripts.execute_formal_reader_behavior_consent_plan._require_clean_worktree",
        ):
            validated = validate_plan(
                "in-memory-plan.json",
                approved_plan_id=str(plan["plan_id"]),
                approved_plan_hash=str(plan["plan_hash"]),
            )
        self.assertEqual(plan, validated)
        tampered = dict(plan)
        tampered["intent"] = "tampered"
        with patch(
            "scripts.execute_formal_reader_behavior_consent_plan._load_json",
            return_value=tampered,
        ), patch(
            "scripts.execute_formal_reader_behavior_consent_plan._current_commit",
            return_value="a" * 40,
        ), patch(
            "scripts.execute_formal_reader_behavior_consent_plan._require_clean_worktree",
        ), self.assertRaises(ValueError):
            validate_plan(
                "in-memory-plan.json",
                approved_plan_id=str(tampered["plan_id"]),
                approved_plan_hash=str(tampered["plan_hash"]),
            )

    def test_duplicate_grant_is_fail_closed(self) -> None:
        identity = json.loads(json.dumps(self.identity))
        identity["consents"][CONSENT_SCOPE] = True
        with patch(
            "scripts.build_formal_reader_behavior_consent_plan.current_git_commit",
            return_value="a" * 40,
        ), patch(
            "scripts.build_formal_reader_behavior_consent_plan.require_clean_worktree",
        ), self.assertRaisesRegex(ValueError, "already has"):
            build_plan(
                run_id="formal-reader-consent-test-002",
                created_at="2026-09-02T00:00:00Z",
                values=self.values,
                counts=self.counts,
                identity=identity,
            )


if __name__ == "__main__":
    unittest.main()
