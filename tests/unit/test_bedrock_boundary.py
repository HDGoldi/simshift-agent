# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

import pytest

from simshift.config import RunConfig
from simshift.decision.coordinator import DecisionCoordinator
from simshift.domain.enums import Action
from simshift.integrations.bedrock import DeterministicLocalExplainer
from simshift.integrations.strands_tools import build_tool_host
from simshift.orchestration.dispatch import DirectDispatcher
from simshift.orchestration.runner import SimshiftRunner
from simshift.orchestration.services import ToolServices
from simshift.scenarios.repository import ScenarioRepository
from simshift.tracing.events import validate_event_sequence
from tests.fakes.decider import InjectedChoiceProvider


def test_tool_host_and_explainer_are_not_invoked_during_dispatch() -> None:
    runtime = ScenarioRepository().load_runtime("BR_PROFILE")
    services = ToolServices(runtime, run_id="a" * 24)
    agent, host_model = build_tool_host(services)
    explainer = DeterministicLocalExplainer()
    DirectDispatcher(agent).dispatch(
        Action.INVESTIGATE_DEVICE,
        incident_id="BR_PROFILE",
        observation_revision=0,
    )
    assert host_model.invocation_count == 0
    assert explainer.invocation_count == 0
    text = explainer.explain(runtime.observable, {"final_status": "ESCALATED"})
    assert "SIMULATED" in text
    assert explainer.invocation_count == 1


def test_explainer_requires_post_dispatch_evidence() -> None:
    runtime = ScenarioRepository().load_runtime("BR_PROFILE")
    with pytest.raises(ValueError, match="already-produced"):
        DeterministicLocalExplainer().explain(runtime.observable, {})


class _BedrockExplainer:
    status = "REAL"
    detail = "injected no-tools Bedrock"
    provider = "Amazon Bedrock"
    region_name = "test-region-1"
    model_reference = "test-model"

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def request_evidence(self, observable, evidence):
        assert observable and evidence
        return {
            "prompt_hash": "a" * 64,
            "provider": self.provider,
            "region": self.region_name,
            "model_reference": self.model_reference,
        }

    def explain(self, observable, evidence):
        assert observable and evidence
        if self.fail:
            raise TimeoutError("injected optional explanation failure")
        return "bedrock explanation"


def _run_with_explainer(explainer: _BedrockExplainer):
    runtime = ScenarioRepository().load_runtime("BR_PROFILE")
    config = RunConfig(
        scenario_id=runtime.observable.incident_id,
        fixture_revision=runtime.fixture_revision,
        seed=runtime.default_seed,
        approval="granted",
    )
    services = ToolServices(runtime, run_id=config.run_id)
    agent, _ = build_tool_host(services)
    coordinator = DecisionCoordinator(
        provider=InjectedChoiceProvider("evaluate_profile_change"),
        dispatcher=DirectDispatcher(agent),
    )
    result = SimshiftRunner(
        runtime=runtime,
        config=config,
        coordinator=coordinator,
        explainer=explainer,
    ).run()
    validate_event_sequence(result.events)
    return result


def test_bedrock_success_is_traced_before_terminal_result() -> None:
    result = _run_with_explainer(_BedrockExplainer())
    assert result.status == "RESTORED"
    assert result.explanation == "bedrock explanation"
    assert result.explanation_error is None
    event_types = [event.event_type for event in result.events]
    assert event_types[-3:] == ["bedrock_request", "bedrock_result", "run_completed"]
    assert result.events[0].payload["provenance"]["explainer_model"]["status"] == "REAL"
    assert result.events[0].payload["provenance"]["explainer_model"]["configured"] is True
    assert result.events[0].payload["provenance"]["explainer_model"]["invoked"] is False
    assert result.events[-1].payload["explainer_invoked"] is True


def test_bedrock_failure_is_traced_without_reversing_simulation() -> None:
    result = _run_with_explainer(_BedrockExplainer(fail=True))
    assert result.status == "RESTORED"
    assert result.final_profile == "profile_B"
    assert result.explanation is None
    assert result.explanation_error == "TimeoutError"
    assert [event.event_type for event in result.events][-3:] == [
        "bedrock_request",
        "bedrock_unavailable",
        "run_completed",
    ]
