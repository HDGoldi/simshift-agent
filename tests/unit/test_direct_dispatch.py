# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

import pytest

from simshift.domain.enums import Action
from simshift.integrations.strands_tools import build_tool_host
from simshift.orchestration.dispatch import DirectDispatcher
from simshift.orchestration.services import ToolServices
from simshift.scenarios.repository import ScenarioRepository


def _runtime_for(action: Action):
    runtime = ScenarioRepository().load_runtime("BR_PROFILE")
    if action is Action.TRY_ALLOWED_OPERATOR:
        operators = tuple(
            operator.model_copy(
                update={"permitted_on_active_profile": True, "available": True}
            )
            if not operator.currently_selected
            else operator
            for operator in runtime.policy.operators
        )
        runtime.policy = runtime.policy.model_copy(update={"operators": operators})
        runtime.observable = runtime.observable.model_copy(
            update={"allowed_alternative_operator_available": True}
        )
    return runtime


@pytest.mark.parametrize("action", list(Action))
def test_each_action_invokes_exact_matching_registered_tool(action: Action) -> None:
    runtime = _runtime_for(action)
    services = ToolServices(runtime, run_id="a" * 24)
    agent, model = build_tool_host(services)
    dispatcher = DirectDispatcher(agent)
    result = dispatcher.dispatch(
        action,
        incident_id="BR_PROFILE",
        observation_revision=0,
    )
    assert result.action is action
    assert services.invocations == [action]
    assert dispatcher.dispatch_count == 1
    assert model.invocation_count == 0
