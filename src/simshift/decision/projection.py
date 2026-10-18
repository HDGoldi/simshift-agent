# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

"""Positive observable-only projections and structural leak checks."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import Enum
from typing import Any

from simshift.domain.enums import HiddenCause
from simshift.domain.models import ActionEffect, EvaluatorTruth, ObservableIncident

_EVALUATOR_KEYS = {
    "_evaluator_truth",
    "evaluator_truth",
    "hidden_cause",
    "acceptable_next_actions",
    "effects",
    "leakage_canary",
}


def observable_projection(observable: ObservableIncident) -> dict[str, Any]:
    """Build a new allowlisted model input from observable fields only."""

    projected: dict[str, Any] = {
        "schema_version": observable.schema_version,
        "incident_id": observable.incident_id.value,
        "observation_revision": observable.observation_revision,
        "country_code": observable.country_code,
        "cohort_size": observable.cohort_size,
        "registration_status": observable.registration_status.value,
        "attach_success_rate": observable.attach_success_rate,
        "telemetry_status": observable.telemetry_status.value,
        "telemetry_ack_rate": observable.telemetry_ack_rate,
        "active_profile_id": observable.active_profile_id,
        "alternative_profile_installed": observable.alternative_profile_installed,
        "allowed_alternative_operator_available": (
            observable.allowed_alternative_operator_available
        ),
        "management_reachability": observable.management_reachability.value,
        "ipa_available": observable.ipa_available,
        "eim_associated": observable.eim_associated,
        "recent_firmware_change": observable.recent_firmware_change,
        "connection_retry_count": observable.connection_retry_count,
        "transition_count": observable.transition_count,
        "action_counts": {
            action.value: observable.action_counts[action] for action in observable.action_counts
        },
        "evidence": [evidence.value for evidence in observable.evidence],
    }
    assert_no_evaluator_leak(projected)
    return projected


def assert_no_evaluator_leak(value: Any, *, canaries: Sequence[str] = ()) -> None:
    """Reject evaluator structures, private paths, and fixture-specific canaries."""

    def visit(item: Any, path: str) -> None:
        if isinstance(item, (EvaluatorTruth, ActionEffect, HiddenCause)):
            raise ValueError(f"evaluator-only type at {path}")
        if isinstance(item, Mapping):
            for key, child in item.items():
                if not isinstance(key, str):
                    raise ValueError(f"non-string key at {path}")
                if key.startswith("_") or key in _EVALUATOR_KEYS:
                    raise ValueError(f"evaluator-only key at {path}.{key}")
                visit(child, f"{path}.{key}")
            return
        if isinstance(item, (list, tuple)):
            for index, child in enumerate(item):
                visit(child, f"{path}[{index}]")
            return
        if isinstance(item, Enum):
            if isinstance(item, HiddenCause):
                raise ValueError(f"hidden cause at {path}")
            visit(item.value, path)
            return
        if isinstance(item, str) and any(canary in item for canary in canaries):
            raise ValueError(f"evaluator canary at {path}")

    visit(value, "$")


# A concise alias for request/explainer integrations.
project_observable = observable_projection
