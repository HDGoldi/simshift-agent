# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

"""Run-scoped services behind the six registered Strands tools."""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import Field

from simshift.decision.filter import filter_actions
from simshift.domain.enums import Action, EvidenceCode, ScenarioId
from simshift.domain.models import LayerCheck, ProfileTransitionProposal, StrictFrozenModel
from simshift.policy.profile_transition import prepare_profile_transition
from simshift.scenarios.repository import IncidentRuntime
from simshift.simulator.engine import SIMULATOR_VERSION, VirtualFleetEngine


class ToolExecution(StrictFrozenModel):
    """Public result returned by every tool closure."""

    action: Action
    tool_call_id: str = Field(min_length=1, max_length=128)
    status: Literal["APPLIED", "PROPOSAL_PREPARED", "ESCALATED", "REJECTED"]
    effect_class: Literal["STATE_CHANGE", "OBSERVATION", "PROPOSAL", "TERMINAL", "NONE"]
    input_revision: int = Field(ge=0, le=64)
    output_revision: int = Field(ge=0, le=64)
    evidence: tuple[EvidenceCode, ...]
    reason: str | None = Field(default=None, max_length=300)
    proposal: ProfileTransitionProposal | None = None
    registration: LayerCheck | None = None
    telemetry: LayerCheck | None = None
    simulator_version: str = SIMULATOR_VERSION


class ToolServices:
    """Resolve fresh incident state before applying one deterministic tool effect."""

    def __init__(self, runtime: IncidentRuntime, *, run_id: str, seed: int | None = None) -> None:
        self.runtime = runtime
        self.run_id = run_id
        self.engine = VirtualFleetEngine(
            runtime.truth_handle,
            runtime.fixture_revision,
            runtime.default_seed if seed is None else seed,
        )
        self.invocations: list[Action] = []

    def resolve(self, *, incident_id: str, observation_revision: int) -> str | None:
        try:
            requested = ScenarioId(incident_id)
        except ValueError:
            return "UNKNOWN_INCIDENT"
        if requested is not self.runtime.observable.incident_id:
            return "UNKNOWN_INCIDENT"
        if observation_revision != self.runtime.observable.observation_revision:
            return "STALE_OBSERVATION"
        return None

    def execute(
        self,
        action: Action,
        *,
        incident_id: str,
        observation_revision: int,
    ) -> ToolExecution:
        """Execute one allowlisted action after freshness and capability checks."""

        with self.runtime.lock:
            reason = self.resolve(
                incident_id=incident_id,
                observation_revision=observation_revision,
            )
            tool_call_id = derive_tool_call_id(self.run_id, action, observation_revision)
            if reason is not None:
                return self._rejected(action, tool_call_id, observation_revision, reason)
            filtered = filter_actions(self.runtime.observable, self.runtime.policy)
            eligible = {option.label for option in filtered.eligible}
            if action.value not in eligible:
                return self._rejected(
                    action,
                    tool_call_id,
                    observation_revision,
                    "CAPABILITY_FILTERED",
                )

            self.invocations.append(action)
            before_evidence = self.runtime.observable.evidence
            proposal = None
            if action is Action.EVALUATE_PROFILE_CHANGE:
                proposal = prepare_profile_transition(
                    self.runtime.observable,
                    self.runtime.policy,
                    run_id=self.run_id,
                    tool_call_id=tool_call_id,
                )
            effect = self.engine.apply_action(self.runtime.observable, action)
            self.runtime.observable = effect.observable
            added = tuple(
                code for code in effect.observable.evidence if code not in before_evidence
            )
            status: Literal["APPLIED", "PROPOSAL_PREPARED", "ESCALATED", "REJECTED"]
            effect_class: Literal[
                "STATE_CHANGE", "OBSERVATION", "PROPOSAL", "TERMINAL", "NONE"
            ]
            if action is Action.EVALUATE_PROFILE_CHANGE:
                status = "PROPOSAL_PREPARED"
                effect_class = "PROPOSAL"
            elif action is Action.ESCALATE_OR_WAIT:
                status = "ESCALATED"
                effect_class = "TERMINAL"
            elif action in {Action.RETRY_CONNECTION, Action.TRY_ALLOWED_OPERATOR}:
                status = "APPLIED"
                effect_class = "STATE_CHANGE"
            else:
                status = "APPLIED"
                effect_class = "OBSERVATION"
            return ToolExecution(
                action=action,
                tool_call_id=tool_call_id,
                status=status,
                effect_class=effect_class,
                input_revision=observation_revision,
                output_revision=effect.observable.observation_revision,
                evidence=added,
                proposal=proposal,
                registration=effect.registration,
                telemetry=effect.telemetry,
            )

    def _rejected(
        self,
        action: Action,
        tool_call_id: str,
        revision: int,
        reason: str,
    ) -> ToolExecution:
        return ToolExecution(
            action=action,
            tool_call_id=tool_call_id,
            status="REJECTED",
            effect_class="NONE",
            input_revision=revision,
            output_revision=self.runtime.observable.observation_revision,
            evidence=(),
            reason=reason,
        )


def derive_tool_call_id(run_id: str, action: Action, revision: int) -> str:
    value = f"tool\0{run_id}\0{action.value}\0{revision}"
    return hashlib.sha256(value.encode()).hexdigest()[:32]


__all__ = ["ToolExecution", "ToolServices", "derive_tool_call_id"]
