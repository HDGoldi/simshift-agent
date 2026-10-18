# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

from simshift.decision.coordinator import DecisionCoordinator
from simshift.domain.enums import Action
from simshift.integrations.strands_tools import build_tool_host
from simshift.orchestration.dispatch import DirectDispatcher
from simshift.orchestration.services import ToolServices
from simshift.scenarios.repository import ScenarioRepository
from tests.fakes.decider import InjectedChoiceProvider


def _coordinator(choice: str, *, confidence: float = 1.0):
    runtime = ScenarioRepository().load_runtime("BR_PROFILE")
    services = ToolServices(runtime, run_id="a" * 24)
    agent, model = build_tool_host(services)
    provider = InjectedChoiceProvider(choice, confidence=confidence)
    coordinator = DecisionCoordinator(
        provider=provider,
        dispatcher=DirectDispatcher(agent),
    )
    return runtime, services, model, provider, coordinator


def test_coordinator_preserves_model_and_effective_choice() -> None:
    runtime, services, model, provider, coordinator = _coordinator(
        Action.INVESTIGATE_DEVICE.value
    )
    result = coordinator.coordinate(runtime.observable, runtime.policy)
    assert result.decision is not None and result.effective is not None
    assert result.decision.model_choice == Action.INVESTIGATE_DEVICE.value
    assert result.effective.effective_choice == Action.INVESTIGATE_DEVICE.value
    assert result.tool_result is not None
    assert provider.call_count == coordinator.decision_count == 1
    assert services.invocations == [Action.INVESTIGATE_DEVICE]
    assert model.invocation_count == 0


def test_low_confidence_choice_fails_closed_to_escalation() -> None:
    runtime, services, _, _, coordinator = _coordinator(
        Action.INVESTIGATE_DEVICE.value,
        confidence=0.0,
    )
    result = coordinator.coordinate(runtime.observable, runtime.policy)
    assert result.effective is not None
    assert result.effective.model_choice == Action.INVESTIGATE_DEVICE.value
    assert result.effective.effective_choice == Action.ESCALATE_OR_WAIT.value
    assert result.effective.override_reason == "LOW_CONFIDENCE"
    assert services.invocations == [Action.ESCALATE_OR_WAIT]
