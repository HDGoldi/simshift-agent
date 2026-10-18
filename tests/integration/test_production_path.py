# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

"""Semantic characterization of the real local production path."""

from __future__ import annotations

from pathlib import Path

import pytest

from simshift.config import RunConfig
from simshift.decision.coordinator import DecisionCoordinator
from simshift.integrations.decider_http import SimshiftDeciderAdapter
from simshift.integrations.strands_tools import build_tool_host
from simshift.orchestration.dispatch import DirectDispatcher
from simshift.orchestration.runner import RunResult, SimshiftRunner
from simshift.orchestration.services import ToolServices
from simshift.scenarios.repository import IncidentRuntime, ScenarioRepository
from simshift.tracing.events import validate_event_sequence
from tests.integration.conftest import require_opt_in

pytestmark = pytest.mark.production_path


def run_real_scenario(
    scenario: str,
    endpoint: tuple[str, Path],
) -> tuple[RunResult, IncidentRuntime, int]:
    origin, manifest = endpoint
    runtime = ScenarioRepository().load_runtime(scenario)
    config = RunConfig(
        scenario_id=runtime.observable.incident_id,
        fixture_revision=runtime.fixture_revision,
        seed=runtime.default_seed,
        approval="granted",
    )
    services = ToolServices(runtime, run_id=config.run_id, seed=config.seed)
    agent, host_model = build_tool_host(services)
    coordinator = DecisionCoordinator(
        provider=SimshiftDeciderAdapter(origin=origin, manifest_path=manifest),
        dispatcher=DirectDispatcher(agent),
        confidence_floor=0.20,
    )
    result = SimshiftRunner(runtime=runtime, config=config, coordinator=coordinator).run()
    validate_event_sequence(result.events)
    return result, runtime, host_model.invocation_count


def test_real_production_path_br_restores_and_offline_stops_safely(
    real_decider_endpoint: tuple[str, Path],
) -> None:
    require_opt_in("SIMSHIFT_RUN_PRODUCTION_PATH")
    br, br_runtime, br_host_calls = run_real_scenario("BR_PROFILE", real_decider_endpoint)
    assert br.status == "RESTORED"
    assert br.reason == "PROFILE_TRANSITION_VERIFIED"
    assert br.final_profile == "profile_B"
    assert br.transition is not None
    assert br_host_calls == 0
    assert {event.event_type for event in br.events} >= {
        "proposal_prepared",
        "approval_consumed",
        "registration_check",
        "telemetry_check",
        "run_completed",
    }
    assert br_runtime.observable.active_profile_id == "profile_B"
    br_tool = next(event for event in br.events if event.event_type == "tool_dispatch_started")
    assert br_tool.payload["tool_name"] == "prepare_guarded_profile_transition"
    assert any(event.event_type == "decider_health_checked" for event in br.events)

    offline, offline_runtime, offline_host_calls = run_real_scenario(
        "OFFLINE", real_decider_endpoint
    )
    assert offline.status == "ESCALATED"
    assert offline.transition is None
    assert offline.final_profile == "profile_A"
    assert offline_host_calls == 0
    assert not offline_runtime.transitions
    assert not offline_runtime.policy.consumed_approval_ids
    assert all(event.event_type != "transition_changed" for event in offline.events)
