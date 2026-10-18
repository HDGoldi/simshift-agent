# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

"""Capability filtering, model/effective policy, and one direct dispatch."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from patterns.capability_aware_router.schemas import (
    ChoiceDecision,
    DecisionPolicy,
    EffectiveDecision,
    FilterResult,
    NoDecision,
    QuestionOption,
)
from simshift.decision.filter import filter_actions
from simshift.domain.enums import Action
from simshift.domain.models import ObservableIncident, PolicyMetadata
from simshift.orchestration.dispatch import DirectDispatcher, EvidenceSink
from simshift.orchestration.services import ToolExecution, derive_tool_call_id


class SimshiftChoiceProvider(Protocol):
    status: str
    detail: str

    @property
    def capacity(self) -> int: ...

    def choose(
        self,
        observable: ObservableIncident,
        options: tuple[QuestionOption, ...],
        *,
        decision_id: str | None = None,
        evidence_sink: EvidenceSink | None = None,
    ) -> ChoiceDecision: ...


@dataclass(frozen=True)
class CoordinatedDecision:
    filtered: FilterResult
    decision: ChoiceDecision | None
    effective: EffectiveDecision | None
    no_decision: NoDecision | None
    tool_result: ToolExecution | None


class DecisionCoordinator:
    """Make at most one Decider request and one matching tool dispatch."""

    def __init__(
        self,
        *,
        provider: SimshiftChoiceProvider,
        dispatcher: DirectDispatcher,
        confidence_floor: float = 0.20,
    ) -> None:
        self.provider = provider
        self.dispatcher = dispatcher
        self.policy = DecisionPolicy(
            min_confidence=confidence_floor,
            fallback_label=Action.ESCALATE_OR_WAIT.value,
        )
        self.decision_count = 0

    def coordinate(
        self,
        observable: ObservableIncident,
        policy_metadata: PolicyMetadata,
        *,
        decision_id: str | None = None,
        run_id: str | None = None,
        evidence_sink: EvidenceSink | None = None,
    ) -> CoordinatedDecision:
        if evidence_sink is not None and (decision_id is None or run_id is None):
            raise ValueError("traced coordination requires decision and run IDs")
        filtered = filter_actions(observable, policy_metadata)
        if evidence_sink is not None:
            evidence_sink(
                "options_filtered",
                {
                    "decision_id": decision_id,
                    "eligible_labels": [item.label for item in filtered.eligible],
                    "removed": [
                        {"label": item.option.label, "reason": item.reason}
                        for item in filtered.removed
                    ],
                },
            )
        count = len(filtered.eligible)
        if count < 2:
            no_decision = NoDecision(
                reason="INSUFFICIENT_CHOICE_CARDINALITY",
                eligible_count=count,
                capacity=self.provider.capacity,
            )
            if evidence_sink is not None:
                evidence_sink(
                    "no_decision",
                    {
                        "decision_id": decision_id,
                        "eligible_count": count,
                        "capacity": self.provider.capacity,
                        "reason": no_decision.reason,
                    },
                )
            tool_result = None
            if count == 1 and filtered.eligible[0].label == Action.ESCALATE_OR_WAIT.value:
                action = Action.ESCALATE_OR_WAIT
                if evidence_sink is not None:
                    evidence_sink(
                        "decision_policy_applied",
                        {
                            "decision_id": decision_id,
                            "model_choice": None,
                            "effective_choice": action.value,
                            "confidence_floor": self.policy.min_confidence,
                            "override_reason": "INSUFFICIENT_CHOICE_CARDINALITY",
                        },
                    )
                tool_result = self._dispatch(
                    action,
                    observable,
                    decision_id=decision_id,
                    run_id=run_id,
                    evidence_sink=evidence_sink,
                )
            return CoordinatedDecision(filtered, None, None, no_decision, tool_result)
        if count > self.provider.capacity:
            no_decision = NoDecision(
                reason="UNSUPPORTED_CHOICE_CARDINALITY",
                eligible_count=count,
                capacity=self.provider.capacity,
            )
            if evidence_sink is not None:
                evidence_sink(
                    "no_decision",
                    {
                        "decision_id": decision_id,
                        "eligible_count": count,
                        "capacity": self.provider.capacity,
                        "reason": no_decision.reason,
                    },
                )
            return CoordinatedDecision(filtered, None, None, no_decision, None)
        decision = self.provider.choose(
            observable,
            filtered.eligible,
            decision_id=decision_id,
            evidence_sink=evidence_sink,
        )
        self.decision_count += 1
        labels = tuple(option.label for option in filtered.eligible)
        effective = self.policy.apply(decision, labels)
        if evidence_sink is not None:
            evidence_sink(
                "decision_policy_applied",
                {
                    "decision_id": decision_id,
                    "model_choice": effective.model_choice,
                    "effective_choice": effective.effective_choice,
                    "confidence_floor": self.policy.min_confidence,
                    "override_reason": effective.override_reason,
                },
            )
        action = Action(effective.effective_choice)
        tool_result = self._dispatch(
            action,
            observable,
            decision_id=decision_id,
            run_id=run_id,
            evidence_sink=evidence_sink,
        )
        return CoordinatedDecision(filtered, decision, effective, None, tool_result)

    def _dispatch(
        self,
        action: Action,
        observable: ObservableIncident,
        *,
        decision_id: str | None,
        run_id: str | None,
        evidence_sink: EvidenceSink | None,
    ) -> ToolExecution:
        expected_tool_call_id = (
            derive_tool_call_id(run_id, action, observable.observation_revision)
            if run_id is not None
            else None
        )
        return self.dispatcher.dispatch(
            action,
            incident_id=observable.incident_id.value,
            observation_revision=observable.observation_revision,
            decision_id=decision_id,
            expected_tool_call_id=expected_tool_call_id,
            evidence_sink=evidence_sink,
        )


__all__ = ["CoordinatedDecision", "DecisionCoordinator", "SimshiftChoiceProvider"]
