# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

"""The six exact Strands tool closures for SIMShift."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from strands import Agent, tool

from simshift.domain.enums import Action
from simshift.integrations.bedrock import LocalTestDoubleModel
from simshift.orchestration.services import ToolServices

EXPECTED_TOOL_NAMES = (
    "simulate_retry_with_backoff",
    "simulate_operator_reselection",
    "query_firmware_modem_diagnostics",
    "query_apn_session_app_diagnostics",
    "prepare_guarded_profile_transition",
    "defer_or_escalate",
)


def build_tools(services: ToolServices) -> tuple[Any, ...]:
    """Create run-scoped, keyword-only closures with no evaluator data."""

    @tool
    def simulate_retry_with_backoff(
        *, incident_id: str, observation_revision: int
    ) -> dict[str, Any]:
        """Run one bounded synthetic connection retry."""
        return services.execute(
            Action.RETRY_CONNECTION,
            incident_id=incident_id,
            observation_revision=observation_revision,
        ).model_dump(mode="json")

    @tool
    def simulate_operator_reselection(
        *, incident_id: str, observation_revision: int
    ) -> dict[str, Any]:
        """Try one permitted synthetic operator reselection."""
        return services.execute(
            Action.TRY_ALLOWED_OPERATOR,
            incident_id=incident_id,
            observation_revision=observation_revision,
        ).model_dump(mode="json")

    @tool
    def query_firmware_modem_diagnostics(
        *, incident_id: str, observation_revision: int
    ) -> dict[str, Any]:
        """Read synthetic cached firmware and modem diagnostics."""
        return services.execute(
            Action.INVESTIGATE_DEVICE,
            incident_id=incident_id,
            observation_revision=observation_revision,
        ).model_dump(mode="json")

    @tool
    def query_apn_session_app_diagnostics(
        *, incident_id: str, observation_revision: int
    ) -> dict[str, Any]:
        """Read synthetic cached data-path diagnostics."""
        return services.execute(
            Action.INVESTIGATE_DATA_PATH,
            incident_id=incident_id,
            observation_revision=observation_revision,
        ).model_dump(mode="json")

    @tool
    def prepare_guarded_profile_transition(
        *, incident_id: str, observation_revision: int
    ) -> dict[str, Any]:
        """Prepare a guarded profile proposal without enabling it."""
        return services.execute(
            Action.EVALUATE_PROFILE_CHANGE,
            incident_id=incident_id,
            observation_revision=observation_revision,
        ).model_dump(mode="json")

    @tool
    def defer_or_escalate(
        *, incident_id: str, observation_revision: int
    ) -> dict[str, Any]:
        """Stop automation safely and escalate or wait."""
        return services.execute(
            Action.ESCALATE_OR_WAIT,
            incident_id=incident_id,
            observation_revision=observation_revision,
        ).model_dump(mode="json")

    return (
        simulate_retry_with_backoff,
        simulate_operator_reselection,
        query_firmware_modem_diagnostics,
        query_apn_session_app_diagnostics,
        prepare_guarded_profile_transition,
        defer_or_escalate,
    )


def build_tool_host(
    services: ToolServices,
    *,
    model: LocalTestDoubleModel | None = None,
    tools: Sequence[Any] | None = None,
) -> tuple[Agent, LocalTestDoubleModel]:
    """Build a real Strands Agent whose inert host model is never invoked."""

    host_model = model or LocalTestDoubleModel()
    registered_tools = tuple(tools) if tools is not None else build_tools(services)
    agent = Agent(
        model=host_model,
        tools=list(registered_tools),
        record_direct_tool_call=False,
        callback_handler=None,
    )
    names = tuple(agent.tool_registry.registry)
    if names != EXPECTED_TOOL_NAMES:
        raise RuntimeError(f"unexpected Strands tool registry: {names!r}")
    return agent, host_model


__all__ = ["EXPECTED_TOOL_NAMES", "build_tool_host", "build_tools"]
