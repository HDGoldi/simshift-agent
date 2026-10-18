# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

from simshift.config import RunConfig
from simshift.decision.coordinator import DecisionCoordinator
from simshift.domain.enums import ProfileState, TransitionState
from simshift.integrations.strands_tools import build_tool_host
from simshift.orchestration.dispatch import DirectDispatcher
from simshift.orchestration.runner import SimshiftRunner
from simshift.orchestration.services import ToolServices
from simshift.scenarios.repository import ScenarioRepository
from simshift.tracing.events import validate_event_sequence
from tests.fakes.decider import InjectedChoiceProvider


def test_approved_deterministic_br_vertical_slice_restores_both_layers() -> None:
    runtime = ScenarioRepository().load_runtime("BR_PROFILE")
    config = RunConfig(
        scenario_id=runtime.observable.incident_id,
        fixture_revision=runtime.fixture_revision,
        seed=runtime.default_seed,
        approval="granted",
    )
    services = ToolServices(runtime, run_id=config.run_id)
    agent, model = build_tool_host(services)
    coordinator = DecisionCoordinator(
        provider=InjectedChoiceProvider("evaluate_profile_change"),
        dispatcher=DirectDispatcher(agent),
    )
    result = SimshiftRunner(
        runtime=runtime,
        config=config,
        coordinator=coordinator,
    ).run()
    assert result.status == "RESTORED"
    assert result.transition is not None
    assert result.transition.states[-1] is TransitionState.SUCCEEDED
    assert runtime.observable.active_profile_id == "profile_B"
    assert sum(p.state is ProfileState.ENABLED for p in runtime.policy.profiles) == 1
    assert {event.event_type for event in result.events} >= {
        "registration_check",
        "telemetry_check",
        "run_completed",
    }
    validate_event_sequence(result.events)
    assert model.invocation_count == 0
