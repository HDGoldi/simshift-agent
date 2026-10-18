# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

import json

import pytest

from simshift.decision.projection import assert_no_evaluator_leak, observable_projection
from simshift.domain.enums import HiddenCause
from simshift.scenarios.repository import ScenarioRepository


def test_projection_contains_only_positive_observable_allowlist() -> None:
    projected = observable_projection(ScenarioRepository().load("BR_PROFILE").observable)
    encoded = json.dumps(projected)
    assert "policy_metadata" not in encoded
    assert "evaluator" not in encoded
    assert "EVAL_ONLY" not in encoded


@pytest.mark.parametrize(
    "value",
    [
        {"_evaluator_truth": {}},
        {"hidden_cause": "x"},
        {"safe": HiddenCause.ACTIVE_PROFILE_INCOMPATIBILITY},
        {"safe": "prefix EVAL_ONLY_BR_7Q9M2K suffix"},
    ],
)
def test_evaluator_structures_and_canary_are_rejected(value: object) -> None:
    with pytest.raises(ValueError):
        assert_no_evaluator_leak(value, canaries=("EVAL_ONLY_BR_7Q9M2K",))
