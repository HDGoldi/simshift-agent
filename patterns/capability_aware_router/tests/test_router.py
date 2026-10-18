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


class RecordingClient:
    def __init__(self, selected_index: int = 0) -> None:
        self.calls = 0
        self.selected_index = selected_index

    def choose(
        self,
        *,
        state: object,
        question: TypedChoiceQuestion,
        expected_model: str,
    ) -> ChoiceDecision:
        self.calls += 1
        selected = question.options[self.selected_index].label
        probabilities = {option.label: 0.0 for option in question.options}
        probabilities[selected] = 1.0
        return ChoiceDecision(
            model=expected_model,
            model_choice=selected,
            probabilities=probabilities,
            confidence=1.0,
            usage=Usage(input_tokens=1, output_tokens=1),
            client_latency_ms=1.0,
        )


def _record(calls: Counter[str], label: str) -> Callable[[], str]:
    def callback() -> str:
        calls.update([label])
        return label

    return callback


def _options(count: int) -> tuple[QuestionOption, ...]:
    return tuple(
        QuestionOption(label=f"a{index}", description=f"Action {index}")
        for index in range(count)
    )


@pytest.mark.parametrize(
    ("count", "expected_reason", "expected_http"),
    [
        (0, "INSUFFICIENT_CHOICE_CARDINALITY", 0),
        (1, "INSUFFICIENT_CHOICE_CARDINALITY", 0),
        (2, None, 1),
        (24, None, 1),
        (25, "UNSUPPORTED_CHOICE_CARDINALITY", 0),
        (255, "UNSUPPORTED_CHOICE_CARDINALITY", 0),
    ],
)
def test_capacity_boundaries_do_not_reduce_or_fabricate_options(
    count: int, expected_reason: str | None, expected_http: int
) -> None:
    options = _options(count)
    filtered = FilterResult.from_partition(options, eligible=options, removed=())
    client = RecordingClient()
    callbacks: Counter[str] = Counter()
    registered = _options(max(count, 1))
    registry = ToolRegistry(
        {option.label: _record(callbacks, option.label) for option in registered}
    )
    router = CapabilityAwareRouter(
        client=client,
        trusted_num_slots=24,
        expected_model="model-v1",
        registry=registry,
        policy=DecisionPolicy(min_confidence=0.20, fallback_label=registered[0].label),
    )
    result = router.route_filtered(
        filtered=filtered,
        state={},
        question_name="next_step",
        instructions="Choose one action.",
    )
    assert client.calls == expected_http
    assert sum(callbacks.values()) == expected_http
    assert len(filtered.eligible) == count
    assert (result.no_decision.reason if result.no_decision else None) == expected_reason


def test_selected_label_dispatches_exactly_one_matching_callback() -> None:
    options = _options(3)
    calls: Counter[str] = Counter()
    router = CapabilityAwareRouter(
        client=RecordingClient(selected_index=1),
        trusted_num_slots=24,
        expected_model="model-v1",
        registry=ToolRegistry(
            {option.label: _record(calls, option.label) for option in options}
        ),
        policy=DecisionPolicy(min_confidence=0.20, fallback_label="a2"),
    )
    result = router.route_filtered(
        filtered=FilterResult.from_partition(options, eligible=options, removed=()),
        state={},
        question_name="next_step",
        instructions="Choose one.",
    )
    assert calls == Counter({"a1": 1})
    assert result.trace.dispatched_label == "a1"
