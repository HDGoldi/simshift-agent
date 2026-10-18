# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

from simshift.config import RunConfig
from simshift.decision.coordinator import DecisionCoordinator
from simshift.domain.enums import Action
from simshift.integrations.strands_tools import build_tool_host
from simshift.orchestration.dispatch import DirectDispatcher
from simshift.orchestration.runner import SimshiftRunner
from simshift.orchestration.services import ToolServices
from simshift.scenarios.repository import ScenarioRepository
from tests.fakes.decider import InjectedChoiceProvider


def test_runner_enforces_four_step_and_one_dispatch_per_decision_bounds() -> None:
    runtime = ScenarioRepository().load_runtime("BR_PROFILE")
    config = RunConfig(
        scenario_id=runtime.observable.incident_id,
        fixture_revision=runtime.fixture_revision,
        seed=runtime.default_seed,
        max_steps=4,
    )
    services = ToolServices(runtime, run_id=config.run_id)
    agent, model = build_tool_host(services)
    provider = InjectedChoiceProvider(
        [
            "investigate_device",
            "investigate_data_path",
            "retry_connection",
            "retry_connection",
        ]
    )
    coordinator = DecisionCoordinator(
        provider=provider,
        dispatcher=DirectDispatcher(agent),
    )
    result = SimshiftRunner(
        runtime=runtime,
        config=config,
        coordinator=coordinator,
    ).run()
    assert result.status == "ESCALATED"
    assert result.reason == "BOUND_EXHAUSTED"
    assert result.steps == result.decision_count == result.dispatch_count == 4
    assert provider.call_count == 4
    assert model.invocation_count == 0


def test_single_safe_escalation_has_null_model_choice() -> None:
    runtime = ScenarioRepository().load_runtime("OFFLINE")
    counts = dict(runtime.observable.action_counts)
    counts[Action.INVESTIGATE_DEVICE] = 1
    counts[Action.INVESTIGATE_DATA_PATH] = 1
    runtime.observable = runtime.observable.model_copy(update={"action_counts": counts})
    config = RunConfig(
        scenario_id=runtime.observable.incident_id,
        fixture_revision=runtime.fixture_revision,
        seed=runtime.default_seed,
    )
    services = ToolServices(runtime, run_id=config.run_id)
    agent, _ = build_tool_host(services)
    provider = InjectedChoiceProvider("escalate_or_wait")
    result = SimshiftRunner(
        runtime=runtime,
        config=config,
        coordinator=DecisionCoordinator(
            provider=provider,
            dispatcher=DirectDispatcher(agent),
        ),
    ).run()
    policy_event = next(
        event for event in result.events if event.event_type == "decision_policy_applied"
    )
    assert provider.call_count == result.decision_count == 0
    assert policy_event.payload == {
        "decision_id": policy_event.payload["decision_id"],
        "model_choice": None,
        "effective_choice": "escalate_or_wait",
        "confidence_floor": 0.2,
        "override_reason": "INSUFFICIENT_CHOICE_CARDINALITY",
    }
