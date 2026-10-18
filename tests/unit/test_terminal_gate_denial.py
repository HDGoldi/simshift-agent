# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

from simshift.config import RunConfig
from simshift.decision.coordinator import DecisionCoordinator
from simshift.integrations.bedrock import DeterministicLocalExplainer
from simshift.integrations.strands_tools import build_tool_host
from simshift.orchestration.dispatch import DirectDispatcher
from simshift.orchestration.runner import SimshiftRunner
from simshift.orchestration.services import ToolServices
from simshift.scenarios.repository import ScenarioRepository
from tests.fakes.decider import InjectedChoiceProvider


def test_final_gate_denial_is_terminal_without_second_decision_or_tool() -> None:
    runtime = ScenarioRepository().load_runtime("BR_PROFILE")
    config = RunConfig(
        scenario_id=runtime.observable.incident_id,
        fixture_revision=runtime.fixture_revision,
        seed=runtime.default_seed,
        approval="denied",
    )
    services = ToolServices(runtime, run_id=config.run_id)
    agent, model = build_tool_host(services)
    provider = InjectedChoiceProvider("evaluate_profile_change")
    coordinator = DecisionCoordinator(
        provider=provider,
        dispatcher=DirectDispatcher(agent),
    )
    explainer = DeterministicLocalExplainer()
    result = SimshiftRunner(
        runtime=runtime,
        config=config,
        coordinator=coordinator,
        explainer=explainer,
    ).run()
    assert result.status == "ESCALATED"
    assert result.reason == "PROFILE_PROPOSAL_BLOCKED"
    assert provider.call_count == result.decision_count == 1
    assert result.dispatch_count == 1
    assert len(runtime.audits) == 1 and not runtime.transitions
    assert [event.event_type for event in result.events][-2:] == [
        "proposal_blocked",
        "run_escalated",
    ]
    assert result.events[-1].payload["explainer_invoked"] is False
    assert result.events[0].payload["provenance"]["explainer_model"] == {
        "status": "LOCAL_TEST_DOUBLE",
        "detail": "deterministic local explanation",
        "configured": True,
        "invoked": False,
    }
    assert explainer.invocation_count == 0
    assert model.invocation_count == 0
