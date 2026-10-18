# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

import pytest

from patterns.capability_aware_router.schemas import ChoiceDecision, DecisionPolicy, Usage


def _decision(confidence: float) -> ChoiceDecision:
    return ChoiceDecision(
        model="model-v1",
        model_choice="inspect",
        probabilities={"inspect": 0.55, "review": 0.45},
        confidence=confidence,
        usage=Usage(input_tokens=2, output_tokens=1),
        client_latency_ms=1.0,
    )


def test_low_confidence_preserves_model_choice_and_uses_fallback() -> None:
    effective = DecisionPolicy(
        min_confidence=0.20, fallback_label="review"
    ).apply(_decision(0.10), ("inspect", "review"))
    assert effective.model_choice == "inspect"
    assert effective.effective_choice == "review"
    assert effective.override_reason == "LOW_CONFIDENCE"


def test_confident_choice_is_unchanged() -> None:
    effective = DecisionPolicy(
        min_confidence=0.20, fallback_label="review"
    ).apply(_decision(0.20), ("inspect", "review"))
    assert effective.effective_choice == "inspect"
    assert effective.override_reason is None


def test_low_confidence_fails_closed_if_fallback_is_forbidden() -> None:
    with pytest.raises(ValueError, match="fallback is not eligible"):
        DecisionPolicy(min_confidence=0.20, fallback_label="forbidden").apply(
            _decision(0.10), ("inspect", "review")
        )
