# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

import pytest
from pydantic import ValidationError

from patterns.capability_aware_router.schemas import (
    ChoiceDecision,
    NoDecision,
    QuestionOption,
    TypedChoiceQuestion,
    Usage,
)


def test_option_and_question_are_strict_and_frozen() -> None:
    option = QuestionOption(label="safe_action", description="A safe action")
    question = TypedChoiceQuestion(
        name="next_step",
        instructions="Choose one.",
        options=(option, QuestionOption(label="escalate", description="Escalate safely")),
    )
    assert question.options[0] is option
    with pytest.raises(ValidationError):
        QuestionOption(label="Unsafe-Action", description="bad")
    with pytest.raises(ValidationError):
        question.name = "changed"


def test_question_rejects_duplicate_and_out_of_range_options() -> None:
    option = QuestionOption(label="same", description="Same")
    with pytest.raises(ValidationError, match="unique"):
        TypedChoiceQuestion(name="q", instructions="Choose.", options=(option, option))
    with pytest.raises(ValidationError):
        TypedChoiceQuestion(name="q", instructions="Choose.", options=(option,))


def test_no_decision_reason_must_match_count() -> None:
    assert NoDecision(
        reason="INSUFFICIENT_CHOICE_CARDINALITY", eligible_count=1, capacity=24
    ).eligible_count == 1
    with pytest.raises(ValidationError):
        NoDecision(
            reason="UNSUPPORTED_CHOICE_CARDINALITY", eligible_count=24, capacity=24
        )


def test_decision_probability_mapping_is_immutable() -> None:
    decision = ChoiceDecision(
        model="model-v1",
        model_choice="a",
        probabilities={"a": 1.0, "b": 0.0},
        confidence=1.0,
        usage=Usage(input_tokens=1, output_tokens=1),
        client_latency_ms=1.0,
    )
    with pytest.raises(TypeError):
        decision.probabilities["a"] = 0.5  # type: ignore[index]
