# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

from collections import Counter
from collections.abc import Callable

import pytest

from patterns.capability_aware_router.router import CapabilityAwareRouter, ToolRegistry
from patterns.capability_aware_router.schemas import (
    ChoiceDecision,
    DecisionPolicy,
    FilterResult,
    QuestionOption,
    TypedChoiceQuestion,
    Usage,
)


class ForbiddenClient:
    def choose(
        self,
        *,
        state: object,
        question: TypedChoiceQuestion,
        expected_model: str,
    ) -> ChoiceDecision:
        return ChoiceDecision(
            model=expected_model,
            model_choice="forbidden",
            probabilities={option.label: 0.5 for option in question.options},
            confidence=0.0,
            usage=Usage(input_tokens=1, output_tokens=1),
            client_latency_ms=1.0,
        )


def _record(calls: Counter[str], label: str) -> Callable[[], None]:
    def callback() -> None:
        calls.update([label])

    return callback


def test_forbidden_model_label_never_dispatches() -> None:
    options = (
        QuestionOption(label="inspect", description="Inspect"),
        QuestionOption(label="review", description="Review"),
    )
    calls: Counter[str] = Counter()
    router = CapabilityAwareRouter(
        client=ForbiddenClient(),
        trusted_num_slots=24,
        expected_model="model-v1",
        registry=ToolRegistry(
            {option.label: _record(calls, option.label) for option in options}
        ),
        policy=DecisionPolicy(min_confidence=0.20, fallback_label="review"),
    )
    with pytest.raises(ValueError, match="model choice is not eligible"):
        router.route_filtered(
            filtered=FilterResult.from_partition(options, eligible=options, removed=()),
            state={},
            question_name="next_step",
            instructions="Choose one.",
        )
    assert not calls
