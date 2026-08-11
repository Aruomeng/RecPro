from __future__ import annotations

import unittest
from datetime import UTC, datetime
from uuid import UUID

from backend.app.recommendation.application.g4_clarification import (
    G4ClarificationError,
    build_g4_clarification_continuation,
)
from backend.app.recommendation.domain.public import RecommendationTaskCommand


QUESTIONS = (
    {
        "slot": "resource_types",
        "options": ["BOOK", "PAPER", "BOOK_AND_PAPER"],
        "required": True,
    },
    {
        "slot": "topic",
        "options": ["多智能体", "推荐系统", "知识图谱"],
        "required": True,
    },
)


def base_command() -> RecommendationTaskCommand:
    return RecommendationTaskCommand(
        request_id=UUID("11111111-1111-1111-1111-111111111111"),
        session_id=UUID("22222222-2222-2222-2222-222222222222"),
        user_id=1001,
        scene="HOME",
        input_text=None,
        resource_types=(),
        output_type=None,
        source_resource_id=42,
        source_item_id=7,
        evaluation_at=datetime(2026, 8, 11, 1, 0, tzinfo=UTC),
        constraints={"availability": "AVAILABLE_BORROW"},
        limit=8,
    )


class G4ClarificationTests(unittest.TestCase):
    def test_builds_next_context_and_preserves_request_identity(self) -> None:
        continuation = build_g4_clarification_continuation(
            base_command(),
            questions=QUESTIONS,
            answers={"resource_types": "BOOK_AND_PAPER", "topic": "多智能体"},
            previous_context_version=1,
        )
        command = continuation.command
        self.assertEqual(2, continuation.context_version)
        self.assertEqual(("BOOK", "PAPER"), command.resource_types)
        self.assertEqual("多智能体", command.input_text)
        self.assertEqual("HOME", command.scene)
        self.assertEqual(UUID("11111111-1111-1111-1111-111111111111"), command.request_id)
        self.assertEqual(UUID("22222222-2222-2222-2222-222222222222"), command.session_id)
        self.assertEqual(42, command.source_resource_id)
        self.assertEqual(7, command.source_item_id)
        self.assertEqual({"availability": "AVAILABLE_BORROW"}, dict(command.constraints))
        self.assertEqual({"resource_types": "BOOK_AND_PAPER", "topic": "多智能体"}, dict(continuation.answers))

    def test_accepts_bounded_custom_multi_topic_text(self) -> None:
        continuation = build_g4_clarification_continuation(
            base_command(),
            questions=QUESTIONS,
            answers={
                "resource_types": "BOOK",
                "topic": "多智能体+推荐系统+知识图谱",
            },
            previous_context_version=1,
        )
        self.assertEqual(("BOOK",), continuation.command.resource_types)
        self.assertEqual("多智能体+推荐系统+知识图谱", continuation.command.input_text)

    def test_rejects_overlong_custom_topic_text(self) -> None:
        with self.assertRaisesRegex(G4ClarificationError, "exceeds 500"):
            build_g4_clarification_continuation(
                base_command(),
                questions=QUESTIONS,
                answers={"resource_types": "BOOK", "topic": "x" * 501},
                previous_context_version=1,
            )

    def test_rejects_stale_or_invalid_context(self) -> None:
        with self.assertRaisesRegex(G4ClarificationError, "previous_context_version"):
            build_g4_clarification_continuation(
                base_command(), questions=QUESTIONS, answers={}, previous_context_version=0
            )

    def test_rejects_missing_unknown_and_unsupported_answers(self) -> None:
        cases = (
            ({"resource_types": "BOOK"}, "required clarification slots are missing"),
            ({"resource_types": "MAGAZINE", "topic": "多智能体"}, "not one of the declared options"),
            ({"resource_types": "BOOK", "topic": "多智能体", "other": "x"}, "unknown clarification slot"),
        )
        for answers, message in cases:
            with self.subTest(answers=answers):
                with self.assertRaisesRegex(G4ClarificationError, message):
                    build_g4_clarification_continuation(
                        base_command(),
                        questions=QUESTIONS,
                        answers=answers,
                        previous_context_version=1,
                    )

    def test_rejects_malformed_question_contract(self) -> None:
        with self.assertRaisesRegex(G4ClarificationError, "duplicate"):
            build_g4_clarification_continuation(
                base_command(),
                questions=(QUESTIONS[0], QUESTIONS[0]),
                answers={"resource_types": "BOOK"},
                previous_context_version=1,
            )


if __name__ == "__main__":
    unittest.main()
