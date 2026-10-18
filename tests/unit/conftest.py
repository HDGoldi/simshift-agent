# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0


import pytest

from simshift.domain.enums import Action, ScenarioId
from simshift.policy.profile_transition import (
    ProfileTransitionProposal,
    materialize_approval,
    prepare_profile_transition,
)
from simshift.scenarios.repository import IncidentRuntime, ScenarioRepository
from simshift.simulator.engine import VirtualFleetEngine


@pytest.fixture
def br_runtime() -> IncidentRuntime:
    return ScenarioRepository().load_runtime(ScenarioId.BR_PROFILE)


@pytest.fixture
def prepared_br(br_runtime: IncidentRuntime) -> tuple[IncidentRuntime, ProfileTransitionProposal]:
    proposal = prepare_profile_transition(
        br_runtime.observable,
        br_runtime.policy,
        run_id="a" * 24,
        tool_call_id="tool-1",
    )
    engine = VirtualFleetEngine(
        br_runtime.truth_handle, br_runtime.fixture_revision, br_runtime.default_seed
    )
    br_runtime.observable = engine.apply_action(
        br_runtime.observable, Action.EVALUATE_PROFILE_CHANGE
    ).observable
    return br_runtime, proposal


@pytest.fixture
def approved_br(prepared_br: tuple[IncidentRuntime, ProfileTransitionProposal]):
    runtime, proposal = prepared_br
    return runtime, proposal, materialize_approval(proposal, granted=True)
