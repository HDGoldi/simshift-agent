# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

"""Fixed direct calls into the registered Strands tool host."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from strands import Agent

from simshift.decision.options import TOOL_NAME_BY_ACTION
from simshift.domain.enums import Action
from simshift.orchestration.services import ToolExecution

EvidenceSink = Callable[[str, dict[str, Any]], None]


class DirectDispatcher:
    """Dispatch only closed enum values through explicit agent.tool methods."""

    def __init__(self, agent: Agent) -> None:
        self.agent = agent
        self.dispatch_count = 0

    def dispatch(
        self,
        action: Action,
        *,
        incident_id: str,
        observation_revision: int,
        decision_id: str | None = None,
        expected_tool_call_id: str | None = None,
        evidence_sink: EvidenceSink | None = None,
    ) -> ToolExecution:
        arguments = {
            "incident_id": incident_id,
            "observation_revision": observation_revision,
        }
        if evidence_sink is not None:
            if decision_id is None or expected_tool_call_id is None:
                raise ValueError("traced dispatch requires decision and tool-call IDs")
            evidence_sink(
                "tool_dispatch_started",
                {
                    "decision_id": decision_id,
                    "tool_call_id": expected_tool_call_id,
                    "action": action.value,
                    "tool_name": TOOL_NAME_BY_ACTION[action],
                    "incident_id": incident_id,
                    "observation_revision": observation_revision,
                },
            )
        if action is Action.RETRY_CONNECTION:
            raw = self.agent.tool.simulate_retry_with_backoff(**arguments)
        elif action is Action.TRY_ALLOWED_OPERATOR:
            raw = self.agent.tool.simulate_operator_reselection(**arguments)
        elif action is Action.INVESTIGATE_DEVICE:
            raw = self.agent.tool.query_firmware_modem_diagnostics(**arguments)
        elif action is Action.INVESTIGATE_DATA_PATH:
            raw = self.agent.tool.query_apn_session_app_diagnostics(**arguments)
        elif action is Action.EVALUATE_PROFILE_CHANGE:
            raw = self.agent.tool.prepare_guarded_profile_transition(**arguments)
        elif action is Action.ESCALATE_OR_WAIT:
            raw = self.agent.tool.defer_or_escalate(**arguments)
        else:  # pragma: no cover - Action is closed
            raise ValueError(f"unsupported action {action!r}")
        result = _decode_tool_result(raw)
        if expected_tool_call_id is not None and result.tool_call_id != expected_tool_call_id:
            raise RuntimeError("Strands tool result has an unexpected tool-call ID")
        self.dispatch_count += 1
        if evidence_sink is not None:
            evidence_sink(
                "tool_dispatch_finished",
                {
                    "tool_call_id": result.tool_call_id,
                    "result": result.model_dump(mode="json"),
                },
            )
        return result


def _decode_tool_result(raw: Any) -> ToolExecution:
    if not isinstance(raw, dict) or raw.get("status") != "success":
        raise RuntimeError("Strands direct tool dispatch failed")
    content = raw.get("content")
    if not isinstance(content, list) or len(content) != 1:
        raise RuntimeError("Strands tool result has an unexpected envelope")
    block = content[0]
    if not isinstance(block, dict) or not isinstance(block.get("text"), str):
        raise RuntimeError("Strands tool result does not contain JSON text")
    try:
        return ToolExecution.model_validate_json(block["text"])
    except (ValueError, json.JSONDecodeError) as error:
        raise RuntimeError("Strands tool result failed schema validation") from error


__all__ = ["DirectDispatcher", "EvidenceSink"]
