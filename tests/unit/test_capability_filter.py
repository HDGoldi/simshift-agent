# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

from simshift.decision.filter import filter_actions
from simshift.scenarios.repository import ScenarioRepository


def _partition(scenario: str):
    parts = ScenarioRepository().load(scenario)
    result = filter_actions(parts.observable, parts.policy)
    return (
        {item.label for item in result.eligible},
        {item.option.label: item.reason for item in result.removed},
    )


def test_offline_removes_all_remote_mutations() -> None:
    eligible, removed = _partition("OFFLINE")
    assert {"retry_connection", "try_allowed_operator", "evaluate_profile_change"} <= set(removed)
    assert removed["retry_connection"] == "REMOTE_COMMAND_PATH_UNAVAILABLE"
    assert removed["evaluate_profile_change"] == "MANAGEMENT_UNREACHABLE"
    assert "escalate_or_wait" in eligible


def test_br_removes_only_unavailable_operator_from_initial_mutations() -> None:
    eligible, removed = _partition("BR_PROFILE")
    assert removed["try_allowed_operator"] == "NO_ALLOWED_ALTERNATE_OPERATOR"
    assert "retry_connection" in eligible
    assert "evaluate_profile_change" in eligible
