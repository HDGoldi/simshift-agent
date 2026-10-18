# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

from simshift.integrations.strands_tools import EXPECTED_TOOL_NAMES, build_tool_host
from simshift.orchestration.services import ToolServices
from simshift.scenarios.repository import ScenarioRepository


def test_exact_six_tools_are_registered_on_real_strands_agent() -> None:
    runtime = ScenarioRepository().load_runtime("BR_PROFILE")
    agent, model = build_tool_host(ToolServices(runtime, run_id="a" * 24))
    assert tuple(agent.tool_registry.registry) == EXPECTED_TOOL_NAMES
    assert model.invocation_count == 0
    for spec in agent.tool_registry.get_all_tools_config().values():
        schema = spec["inputSchema"]["json"]
        assert set(schema["properties"]) == {"incident_id", "observation_revision"}
        assert set(schema["required"]) == {"incident_id", "observation_revision"}
