# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

"""Label-agnostic causal wiring against the real local Decider."""

from __future__ import annotations

from pathlib import Path

import pytest

from simshift.decision.coordinator import DecisionCoordinator
from simshift.integrations.decider_http import SimshiftDeciderAdapter
from simshift.integrations.strands_tools import build_tool_host
from simshift.orchestration.dispatch import DirectDispatcher
from simshift.orchestration.services import ToolServices
from simshift.scenarios.repository import ScenarioRepository
from tests.integration.conftest import require_opt_in

pytestmark = pytest.mark.real_decider


def test_actual_decider_label_dispatches_its_matching_strands_tool(
    real_decider_endpoint: tuple[str, Path],
) -> None:
    require_opt_in("SIMSHIFT_RUN_REAL_DECIDER")
    origin, manifest = real_decider_endpoint
    runtime = ScenarioRepository().load_runtime("BR_PROFILE")
    adapter = SimshiftDeciderAdapter(origin=origin, manifest_path=manifest)
    services = ToolServices(runtime, run_id="0" * 24, seed=runtime.default_seed)
    agent, host_model = build_tool_host(services)
    dispatcher = DirectDispatcher(agent)
    outcome = DecisionCoordinator(
        provider=adapter,
        dispatcher=dispatcher,
        confidence_floor=0.0,
    ).coordinate(runtime.observable, runtime.policy)

    assert outcome.decision is not None
    assert outcome.effective is not None
    assert outcome.tool_result is not None
    assert outcome.effective.effective_choice == outcome.decision.model_choice
    assert outcome.tool_result.action.value == outcome.decision.model_choice
    assert dispatcher.dispatch_count == 1
    assert host_model.invocation_count == 0
    assert adapter.health is not None
    assert adapter.health.num_slots == 24
    evidence = {item["event"]: item for item in adapter.evidence}
    assert evidence["decider_request"]["request"]["questions"]["next_recovery_step"][
        "criteria"
    ].keys() >= {outcome.decision.model_choice}
    assert evidence["decider_response"]["body"]["answers"]["next_recovery_step"][
        "choice"
    ] == outcome.decision.model_choice
    assert evidence["decider_health_checked"]["consistent"] is True
