# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

"""Bounded, non-recursive production orchestration for one incident run."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from simshift.config import EnvironmentEvidence, RunConfig
from simshift.decision.coordinator import DecisionCoordinator
from simshift.domain.enums import GateReason
from simshift.domain.models import BlockedProposalAudit, LayerCheck, TransitionRecord
from simshift.orchestration.services import ToolExecution
from simshift.policy.profile_transition import (
    TransitionCoordinator,
    materialize_approval,
)
from simshift.scenarios.repository import IncidentRuntime
from simshift.simulator.euicc import EuiccDispatchResult, VirtualEuiccEngine
from simshift.tracing.events import ComponentStatus, EventType, TraceEvent


class Explainer(Protocol):
    status: str
    detail: str
    provider: str
    region_name: str
    model_reference: str

    def explain(self, observable: Any, evidence: Mapping[str, Any]) -> str: ...

    def request_evidence(
        self, observable: Any, evidence: Mapping[str, Any]
    ) -> dict[str, str]: ...


@dataclass(frozen=True)
class RunResult:
    status: Literal["RESTORED", "ESCALATED"]
    reason: str
    final_profile: str
    steps: int
    decision_count: int
    dispatch_count: int
    events: tuple[TraceEvent, ...]
    explanation: str | None = None
    explanation_error: str | None = None
    transition: TransitionRecord | None = None
    blocked: BlockedProposalAudit | None = None


class SimshiftRunner:
    """Run at most four decisions with one dispatch per decision."""

    def __init__(
        self,
        *,
        runtime: IncidentRuntime,
        config: RunConfig,
        coordinator: DecisionCoordinator,
        environment_evidence: EnvironmentEvidence | None = None,
        explainer: Explainer | None = None,
    ) -> None:
        self.runtime = runtime
        self.config = config
        self.coordinator = coordinator
        if environment_evidence is None:
            explainer_mode: Literal["local-test-double", "bedrock"] = (
                "bedrock"
                if explainer is not None and explainer.status == ComponentStatus.REAL.value
                else "local-test-double"
            )
            bedrock_region = None
            bedrock_model_reference = None
            if explainer_mode == "bedrock":
                if explainer is None:
                    raise ValueError("Bedrock environment evidence requires an explainer")
                bedrock_region = explainer.region_name
                bedrock_model_reference = explainer.model_reference
            environment_evidence = EnvironmentEvidence(
                lockfile_sha256=hashlib.sha256(b"simshift-in-memory-test-lock").hexdigest(),
                explainer_mode=explainer_mode,
                bedrock_region=bedrock_region,
                bedrock_model_reference=bedrock_model_reference,
                dependency_versions={"execution": "in-memory-test"},
            )
        self.environment_evidence = environment_evidence
        self.explainer = explainer
        self._explainer_invoked = False
        self._events: list[TraceEvent] = []

    def run(self) -> RunResult:
        self._append(
            "run_started",
            "runner",
            ComponentStatus.SIMULATED,
            {
                "behavior_config_hash": self.config.behavior_config_hash,
                "environment_evidence_hash": (
                    self.environment_evidence.environment_evidence_hash
                ),
                "environment_evidence": self.environment_evidence.model_dump(mode="json"),
                "fixture_revision": self.runtime.fixture_revision,
                "seed": self.config.seed,
                "bounds": {"max_steps": self.config.max_steps},
                "provenance": {
                    "decider": {
                        "status": self.coordinator.provider.status,
                        "detail": self.coordinator.provider.detail,
                    },
                    "strands_framework_dispatch": {
                        "status": "REAL",
                        "detail": "direct registered tool dispatch",
                    },
                    "strands_tool_host_model": {
                        "status": "LOCAL_TEST_DOUBLE",
                        "detail": "inert local host model",
                        "invoked": False,
                    },
                    "explainer_model": {
                        "status": self.explainer.status if self.explainer else "LOCAL_TEST_DOUBLE",
                        "detail": self.explainer.detail if self.explainer else "not configured",
                        "configured": self.explainer is not None,
                        "invoked": False,
                    },
                    "telecom_simulator": {
                        "status": "SIMULATED",
                        "detail": "seeded virtual fleet",
                    },
                    "aws_deployment": {
                        "status": "UNVERIFIED",
                        "detail": "not invoked",
                    },
                },
                "scenario_id": self.config.scenario_id.value,
                "approval": self.config.approval,
            },
        )
        for step in range(1, self.config.max_steps + 1):
            observable = self.runtime.observable
            decision_id = hashlib.sha256(
                f"decision\0{self.config.run_id}\0{step}".encode()
            ).hexdigest()[:32]
            self._append(
                "state_observed",
                "runner",
                ComponentStatus.SIMULATED,
                {
                    "observation_revision": observable.observation_revision,
                    "state": observable.model_dump(mode="json"),
                    "state_hash": hashlib.sha256(
                        observable.model_dump_json().encode()
                    ).hexdigest(),
                },
            )
            outcome = self.coordinator.coordinate(
                observable,
                self.runtime.policy,
                decision_id=decision_id,
                run_id=self.config.run_id,
                evidence_sink=self._record_operation,
            )
            tool_result = outcome.tool_result
            if tool_result is None:
                return self._escalated("NO_DISPATCH", step)
            if tool_result.status == "REJECTED":
                return self._escalated(tool_result.reason or "TOOL_REJECTED", step)
            if tool_result.status == "ESCALATED":
                return self._escalated("SAFE_TOOL_ESCALATION", step)
            if tool_result.registration is not None and tool_result.telemetry is not None:
                self._record_checks(
                    tool_result.tool_call_id,
                    tool_result.registration,
                    tool_result.telemetry,
                )
                if tool_result.registration.passed and tool_result.telemetry.passed:
                    return self._restored(
                        "ACTION_CHECKS_PASSED",
                        step,
                        registration_id=tool_result.registration.check_id,
                        telemetry_id=tool_result.telemetry.check_id,
                    )
            if tool_result.proposal is not None:
                return self._handle_proposal(step, tool_result)
        return self._escalated("BOUND_EXHAUSTED", self.config.max_steps)

    def _record_operation(self, event_type: str, payload: dict[str, Any]) -> None:
        if event_type.startswith("decider_"):
            component = "decider"
            status = ComponentStatus(self.coordinator.provider.status)
        elif event_type.startswith("tool_dispatch_"):
            component = "strands"
            status = ComponentStatus.REAL
        else:
            component = "decision"
            status = ComponentStatus.SIMULATED
        self._append(event_type, component, status, payload)  # type: ignore[arg-type]

    def _handle_proposal(self, step: int, tool_result: ToolExecution) -> RunResult:
        proposal = tool_result.proposal
        if proposal is None:
            raise RuntimeError("profile result has no proposal")
        self._append(
            "proposal_prepared",
            "policy",
            ComponentStatus.SIMULATED,
            {
                "tool_call_id": proposal.tool_call_id,
                "proposal_id": proposal.proposal_id,
                "incident_id": proposal.incident_id.value,
                "source_profile_id": proposal.source_profile_id,
                "target_profile_id": proposal.target_profile_id,
                "run_id": proposal.run_id,
                "basis_observation_revision": proposal.basis_observation_revision,
                "prepared_observation_revision": proposal.prepared_observation_revision,
            },
        )
        approval = materialize_approval(
            proposal,
            granted=self.config.approval == "granted",
        )
        self._append(
            "approval_materialized",
            "policy",
            ComponentStatus.SIMULATED,
            {
                "proposal_id": proposal.proposal_id,
                "approval_id": approval.approval_id,
                "run_id": approval.run_id,
                "incident_id": approval.incident_id.value,
                "source_profile_id": approval.source_profile_id,
                "target_profile_id": approval.target_profile_id,
                "status": approval.status,
                "source": "scripted_simulated_intent",
            },
        )
        committed = TransitionCoordinator(self.runtime).commit(proposal, approval)
        for phase, gates in (("PREVIEW", committed.preview), ("FINAL", committed.final)):
            for gate in gates:
                self._append(
                    "gate_evaluated",
                    "policy",
                    ComponentStatus.SIMULATED,
                    {
                        "proposal_id": proposal.proposal_id,
                        "phase": phase,
                        "gate": gate.gate.value,
                        "passed": gate.passed,
                        "reason": gate.reason.value,
                        "detail": gate.detail,
                    },
                )
        if isinstance(committed.outcome, BlockedProposalAudit):
            blocked = committed.outcome
            self._append(
                "proposal_blocked",
                "policy",
                ComponentStatus.SIMULATED,
                {
                    "proposal_id": proposal.proposal_id,
                    "final_reasons": [
                        gate.reason.value
                        for gate in blocked.final_gate_results
                        if gate.reason is not GateReason.PASS
                    ],
                    "command_created": False,
                    "approval_consumed": False,
                },
            )
            return self._escalated(
                "PROFILE_PROPOSAL_BLOCKED",
                step,
                blocked=blocked,
            )
        transition = committed.outcome
        self._append(
            "approval_consumed",
            "policy",
            ComponentStatus.SIMULATED,
            {
                "proposal_id": proposal.proposal_id,
                "transition_id": transition.transition_id,
                "approval_id": transition.approval_id,
            },
        )
        euicc = VirtualEuiccEngine(self.runtime, seed=self.config.seed).dispatch(
            transition.transition_id
        )
        self._record_transition(euicc)
        if euicc.recovery is not None and euicc.recovery.service_restored:
            return self._restored(
                "PROFILE_TRANSITION_VERIFIED",
                step,
                transition=euicc.transition,
                registration_id=euicc.registration.check_id if euicc.registration else None,
                telemetry_id=euicc.telemetry.check_id if euicc.telemetry else None,
            )
        return self._escalated(
            "PROFILE_TRANSITION_NOT_RESTORED",
            step,
            transition=euicc.transition,
        )

    def _record_transition(self, result: EuiccDispatchResult) -> None:
        states = result.transition.states
        for prior, new in zip(states, states[1:], strict=False):
            self._append(
                "transition_changed",
                "euicc",
                ComponentStatus.SIMULATED,
                {
                    "proposal_id": result.transition.proposal_id,
                    "transition_id": result.transition.transition_id,
                    "tool_call_id": result.transition.tool_call_id,
                    "prior_state": prior.value,
                    "new_state": new.value,
                },
            )
        if result.registration is not None and result.telemetry is not None:
            self._record_checks(
                result.transition.transition_id,
                result.registration,
                result.telemetry,
            )

    def _record_checks(
        self,
        cause_id: str,
        registration: LayerCheck,
        telemetry: LayerCheck,
    ) -> None:
        checks: tuple[tuple[EventType, LayerCheck], ...] = (
            ("registration_check", registration),
            ("telemetry_check", telemetry),
        )
        for event_type, check in checks:
            self._append(
                event_type,
                "verification",
                ComponentStatus.SIMULATED,
                {
                    "check_id": check.check_id,
                    "cause_id": cause_id,
                    "occurrence": 1,
                    "passed_count": check.passed_count,
                    "cohort_size": check.cohort_size,
                    "rate": check.rate,
                    "threshold": check.threshold,
                    "passed": check.passed,
                },
            )

    def _explain_terminal(
        self, status: str, reason: str, step: int
    ) -> tuple[str | None, str | None]:
        if self.explainer is None:
            return None, None
        evidence = {
            "final_status": status,
            "reason": reason,
            "steps": step,
            "decision_count": self.coordinator.decision_count,
            "dispatch_count": self.coordinator.dispatcher.dispatch_count,
        }
        if self.explainer.status != ComponentStatus.REAL.value:
            self._explainer_invoked = True
            return self.explainer.explain(self.runtime.observable, evidence), None
        explanation_id = hashlib.sha256(
            f"explanation\0{self.config.run_id}".encode()
        ).hexdigest()[:32]
        request = self.explainer.request_evidence(self.runtime.observable, evidence)
        self._append(
            "bedrock_request",
            "explainer",
            ComponentStatus.REAL,
            {"explanation_id": explanation_id, **request},
        )
        try:
            self._explainer_invoked = True
            text = self.explainer.explain(self.runtime.observable, evidence)
        except Exception as error:  # optional explanation cannot reverse simulation state
            error_class = type(error).__name__
            self._append(
                "bedrock_unavailable",
                "explainer",
                ComponentStatus.REAL,
                {"explanation_id": explanation_id, "error_class": error_class},
            )
            return None, error_class
        self._append(
            "bedrock_result",
            "explainer",
            ComponentStatus.REAL,
            {"explanation_id": explanation_id, "text": text},
        )
        return text, None

    def _restored(
        self,
        reason: str,
        step: int,
        *,
        transition: TransitionRecord | None = None,
        registration_id: str | None = None,
        telemetry_id: str | None = None,
    ) -> RunResult:
        explanation, explanation_error = self._explain_terminal("RESTORED", reason, step)
        self._append(
            "run_completed",
            "runner",
            ComponentStatus.SIMULATED,
            {
                "reason": reason,
                "latest_registration_check_id": registration_id,
                "latest_telemetry_check_id": telemetry_id,
                "final_profile": self.runtime.observable.active_profile_id,
                "final_status": "RESTORED",
                "explainer_invoked": self._explainer_invoked,
            },
        )
        return RunResult(
            "RESTORED",
            reason,
            self.runtime.observable.active_profile_id,
            step,
            self.coordinator.decision_count,
            self.coordinator.dispatcher.dispatch_count,
            tuple(self._events),
            explanation=explanation,
            explanation_error=explanation_error,
            transition=transition,
        )

    def _escalated(
        self,
        reason: str,
        step: int,
        *,
        transition: TransitionRecord | None = None,
        blocked: BlockedProposalAudit | None = None,
    ) -> RunResult:
        if reason == "PROFILE_PROPOSAL_BLOCKED":
            explanation, explanation_error = None, None
        else:
            explanation, explanation_error = self._explain_terminal("ESCALATED", reason, step)
        self._append(
            "run_escalated",
            "runner",
            ComponentStatus.SIMULATED,
            {
                "reason": reason,
                "final_profile": self.runtime.observable.active_profile_id,
                "final_status": "ESCALATED",
                "explainer_invoked": self._explainer_invoked,
            },
        )
        return RunResult(
            "ESCALATED",
            reason,
            self.runtime.observable.active_profile_id,
            step,
            self.coordinator.decision_count,
            self.coordinator.dispatcher.dispatch_count,
            tuple(self._events),
            explanation=explanation,
            explanation_error=explanation_error,
            transition=transition,
            blocked=blocked,
        )

    def _append(
        self,
        event_type: EventType,
        component: str,
        status: ComponentStatus,
        payload: dict[str, Any],
    ) -> None:
        self._events.append(
            TraceEvent.create(
                run_id=self.config.run_id,
                sequence=len(self._events),
                event_type=event_type,
                component=component,
                component_status=status,
                payload=payload,
            )
        )


__all__ = ["RunResult", "SimshiftRunner"]
