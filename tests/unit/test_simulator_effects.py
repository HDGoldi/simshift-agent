# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

from simshift.domain.enums import Action
from simshift.scenarios.repository import ScenarioRepository
from simshift.simulator.engine import VirtualFleetEngine, deterministic_pass_count


def test_profile_effect_produces_occurrence_indexed_dual_counts() -> None:
    parts = ScenarioRepository().load("BR_PROFILE")
    engine = VirtualFleetEngine(parts.truth_handle, parts.fixture_revision, parts.default_seed)
    result = engine.apply_profile_effect(parts.observable, cause="transition")
    assert result.registration is not None and result.telemetry is not None
    assert result.registration.passed_count == deterministic_pass_count(
        fixture_revision=parts.fixture_revision,
        seed=parts.default_seed,
        action=Action.EVALUATE_PROFILE_CHANGE,
        occurrence=1,
        check="registration",
        cohort_size=parts.observable.cohort_size,
        probability=0.995,
    )
    assert result.telemetry.passed


def test_diagnostic_changes_only_revision_count_and_evidence() -> None:
    parts = ScenarioRepository().load("BR_PROFILE")
    result = VirtualFleetEngine(
        parts.truth_handle, parts.fixture_revision, parts.default_seed
    ).apply_action(parts.observable, Action.INVESTIGATE_DEVICE)
    assert result.observable.observation_revision == 1
    assert result.observable.attach_success_rate == parts.observable.attach_success_rate
    assert result.registration is result.telemetry is None
