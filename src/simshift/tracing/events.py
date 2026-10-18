# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

"""Strict event envelopes, provenance, and causal-link validation."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from patterns.capability_aware_router.decider_client import (
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    DeciderProtocolError,
    decode_json_object,
)
from simshift.config import EnvironmentEvidence
from simshift.decision.options import TOOL_NAME_BY_ACTION
from simshift.decision.projection import assert_no_evaluator_leak
from simshift.domain.enums import Action
from simshift.domain.models import StrictFrozenModel


class ComponentStatus(StrEnum):
    REAL = "REAL"
    LOCAL_TEST_DOUBLE = "LOCAL_TEST_DOUBLE"
    SIMULATED = "SIMULATED"
    UNVERIFIED = "UNVERIFIED"


EventType = Literal[
    "run_started",
    "state_observed",
    "options_filtered",
    "decider_health_checked",
    "decider_retry",
    "decider_request",
    "decider_response",
    "no_decision",
    "decision_policy_applied",
    "tool_dispatch_started",
    "tool_dispatch_finished",
    "proposal_prepared",
    "approval_materialized",
    "gate_evaluated",
    "proposal_blocked",
    "approval_consumed",
    "transition_changed",
    "duplicate_suppressed",
    "registration_check",
    "telemetry_check",
    "bedrock_request",
    "bedrock_result",
    "bedrock_unavailable",
    "run_escalated",
    "run_failed",
    "run_completed",
]

_REQUIRED_KEYS: dict[str, set[str]] = {
    "run_started": {
        "behavior_config_hash",
        "environment_evidence_hash",
        "environment_evidence",
        "fixture_revision",
        "seed",
        "bounds",
        "provenance",
    },
    "state_observed": {"observation_revision", "state", "state_hash"},
    "options_filtered": {"decision_id", "eligible_labels", "removed"},
    "decider_health_checked": {
        "manifest_hash",
        "expected",
        "actual",
        "consistent",
        "response_hash",
        "response_body_utf8",
        "body",
    },
    "decider_retry": {"operation", "decision_id", "attempt", "error_class", "retrying"},
    "decider_request": {
        "decision_id",
        "request_hash",
        "request_body_utf8",
        "request",
        "attempt",
    },
    "decider_response": {
        "decision_id",
        "response_hash",
        "response_body_utf8",
        "body",
        "model_choice",
        "probabilities",
        "confidence",
        "usage",
    },
    "no_decision": {"decision_id", "eligible_count", "capacity", "reason"},
    "decision_policy_applied": {
        "decision_id",
        "model_choice",
        "effective_choice",
        "confidence_floor",
        "override_reason",
    },
    "tool_dispatch_started": {
        "decision_id",
        "tool_call_id",
        "action",
        "tool_name",
        "incident_id",
        "observation_revision",
    },
    "tool_dispatch_finished": {"tool_call_id", "result"},
    "proposal_prepared": {
        "tool_call_id",
        "proposal_id",
        "incident_id",
        "source_profile_id",
        "target_profile_id",
    },
    "approval_materialized": {
        "proposal_id",
        "approval_id",
        "run_id",
        "incident_id",
        "source_profile_id",
        "target_profile_id",
        "status",
        "source",
    },
    "gate_evaluated": {"proposal_id", "phase", "gate", "passed", "reason"},
    "proposal_blocked": {"proposal_id", "final_reasons", "command_created"},
    "approval_consumed": {"proposal_id", "transition_id", "approval_id"},
    "transition_changed": {
        "proposal_id",
        "transition_id",
        "tool_call_id",
        "prior_state",
        "new_state",
    },
    "duplicate_suppressed": {"operation", "existing_state"},
    "registration_check": {
        "check_id",
        "cause_id",
        "occurrence",
        "passed_count",
        "rate",
        "threshold",
        "passed",
    },
    "telemetry_check": {
        "check_id",
        "cause_id",
        "occurrence",
        "passed_count",
        "rate",
        "threshold",
        "passed",
    },
    "bedrock_request": {"explanation_id", "prompt_hash", "provider", "region", "model_reference"},
    "bedrock_result": {"explanation_id", "text"},
    "bedrock_unavailable": {"explanation_id", "error_class"},
    "run_escalated": {"reason", "final_profile", "final_status", "explainer_invoked"},
    "run_failed": {"reason", "final_profile", "final_status", "explainer_invoked"},
    "run_completed": {
        "reason",
        "latest_registration_check_id",
        "latest_telemetry_check_id",
        "final_profile",
        "final_status",
        "explainer_invoked",
    },
}

_OPTIONAL_KEYS: dict[str, set[str]] = {
    "run_started": {"scenario_id", "approval"},
    "decider_health_checked": {"attempt"},
    "decider_response": {"latency_ms", "client_latency_ms", "extensions"},
    "proposal_prepared": {
        "run_id",
        "basis_observation_revision",
        "prepared_observation_revision",
    },
    "gate_evaluated": {"detail"},
    "proposal_blocked": {"approval_consumed"},
    "duplicate_suppressed": {"proposal_id", "transition_id"},
    "registration_check": {"cohort_size"},
    "telemetry_check": {"cohort_size"},
    "bedrock_result": {"usage", "latency_ms"},
    "run_escalated": {
        "latest_registration_check_id",
        "latest_telemetry_check_id",
    },
    "run_failed": {
        "latest_registration_check_id",
        "latest_telemetry_check_id",
    },
}


class ProvenanceEntry(StrictFrozenModel):
    status: ComponentStatus
    detail: str = Field(min_length=1, max_length=300)
    configured: bool | None = None
    invoked: bool | None = None


class RunProvenance(StrictFrozenModel):
    decider: ProvenanceEntry
    strands_framework_dispatch: ProvenanceEntry
    strands_tool_host_model: ProvenanceEntry
    explainer_model: ProvenanceEntry
    telecom_simulator: ProvenanceEntry
    aws_deployment: ProvenanceEntry

    @model_validator(mode="after")
    def validate_local_separation(self) -> RunProvenance:
        if self.strands_framework_dispatch.status is not ComponentStatus.REAL:
            raise ValueError("Strands framework dispatch must be disclosed as REAL")
        if self.strands_tool_host_model.status is not ComponentStatus.LOCAL_TEST_DOUBLE:
            raise ValueError("the inert local tool-host model must be disclosed separately")
        if self.strands_tool_host_model.invoked is not False:
            raise ValueError("the local tool-host model must remain uninvoked")
        if self.explainer_model.configured is None:
            raise ValueError("explainer provenance must disclose whether it is configured")
        if self.explainer_model.invoked is not False:
            raise ValueError("run-start provenance cannot predict an explainer invocation")
        return self


def _decode_exact_json_body(
    payload: dict[str, Any],
    *,
    body_field: str,
    hash_field: str,
    size_limit: int,
) -> dict[str, Any]:
    text = payload.get(body_field)
    digest = payload.get(hash_field)
    if not isinstance(text, str):
        raise ValueError(f"{body_field} must be an exact UTF-8 string")
    if not isinstance(digest, str) or len(digest) != 64:
        raise ValueError(f"{hash_field} must be a SHA-256 digest")
    raw = text.encode("utf-8")
    if len(raw) > size_limit:
        raise ValueError(f"{body_field} exceeds its transport limit")
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError(f"{hash_field} does not match the retained exact body")
    try:
        return decode_json_object(raw)
    except DeciderProtocolError as error:
        raise ValueError(f"{body_field} is not strict duplicate-free finite JSON") from error


def _validate_decider_wire_event(event_type: str, payload: dict[str, Any]) -> None:
    if event_type == "decider_health_checked":
        decoded = _decode_exact_json_body(
            payload,
            body_field="response_body_utf8",
            hash_field="response_hash",
            size_limit=MAX_RESPONSE_BYTES,
        )
        if decoded != payload.get("body"):
            raise ValueError("retained health body does not match its decoded projection")
        actual = payload.get("actual")
        if not isinstance(actual, dict) or any(
            decoded.get(key) != value for key, value in actual.items()
        ):
            raise ValueError("retained health body does not match recorded actual fields")
    elif event_type == "decider_request":
        decoded = _decode_exact_json_body(
            payload,
            body_field="request_body_utf8",
            hash_field="request_hash",
            size_limit=MAX_REQUEST_BYTES,
        )
        if decoded != payload.get("request"):
            raise ValueError("retained request body does not match its decoded projection")
    elif event_type == "decider_response":
        decoded = _decode_exact_json_body(
            payload,
            body_field="response_body_utf8",
            hash_field="response_hash",
            size_limit=MAX_RESPONSE_BYTES,
        )
        if decoded != payload.get("body"):
            raise ValueError("retained response body does not match its decoded projection")
        answers = decoded.get("answers")
        if not isinstance(answers, dict):
            raise ValueError("retained response has no answers object")
        answer = answers.get("next_recovery_step")
        if not isinstance(answer, dict):
            raise ValueError("retained response has no choice answer")
        recorded = {
            "choice": payload.get("model_choice"),
            "probabilities": payload.get("probabilities"),
            "confidence": payload.get("confidence"),
        }
        if any(answer.get(key) != value for key, value in recorded.items()):
            raise ValueError("retained response choice fields do not match recorded decision data")
        if decoded.get("usage") != payload.get("usage"):
            raise ValueError("retained response usage does not match recorded decision data")
        if "latency_ms" in decoded and decoded["latency_ms"] != payload.get("latency_ms"):
            raise ValueError("retained response latency does not match recorded decision data")


class TraceEvent(StrictFrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    event_id: str = Field(pattern=r"^[0-9a-f]{24}:[0-9]{6}$")
    run_id: str = Field(pattern=r"^[0-9a-f]{24}$")
    sequence: int = Field(ge=0)
    logical_time: int = Field(ge=0)
    event_type: EventType
    component: str = Field(min_length=1, max_length=64)
    component_status: ComponentStatus
    payload: dict[str, Any]
    wall_time_utc: str | None = None
    duration_ms: float | None = Field(default=None, ge=0.0)

    @model_validator(mode="after")
    def validate_event(self) -> TraceEvent:
        if self.event_id != f"{self.run_id}:{self.sequence:06d}":
            raise ValueError("event_id must derive from run_id and sequence")
        payload_keys = set(self.payload)
        missing = _REQUIRED_KEYS[self.event_type] - payload_keys
        if missing:
            raise ValueError(f"{self.event_type} payload missing keys: {sorted(missing)}")
        allowed = _REQUIRED_KEYS[self.event_type] | _OPTIONAL_KEYS.get(self.event_type, set())
        unknown = payload_keys - allowed
        if unknown:
            raise ValueError(f"{self.event_type} payload has unknown keys: {sorted(unknown)}")
        assert_no_evaluator_leak(self.payload)
        if self.event_type == "run_started":
            RunProvenance.model_validate_json(json.dumps(self.payload["provenance"]))
            environment = EnvironmentEvidence.model_validate(
                self.payload["environment_evidence"]
            )
            if environment.environment_evidence_hash != self.payload["environment_evidence_hash"]:
                raise ValueError("environment evidence hash does not match its retained inputs")
        _validate_decider_wire_event(self.event_type, self.payload)
        if self.event_type in {"run_escalated", "run_failed", "run_completed"} and not isinstance(
            self.payload["explainer_invoked"], bool
        ):
            raise ValueError("terminal explainer_invoked must be a boolean")
        if self.event_type == "proposal_blocked" and self.payload["command_created"] is not False:
            raise ValueError("a blocked proposal cannot create a command")
        return self

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        sequence: int,
        event_type: EventType,
        component: str,
        component_status: ComponentStatus,
        payload: dict[str, Any],
        logical_time: int | None = None,
    ) -> TraceEvent:
        return cls(
            event_id=f"{run_id}:{sequence:06d}",
            run_id=run_id,
            sequence=sequence,
            logical_time=sequence if logical_time is None else logical_time,
            event_type=event_type,
            component=component,
            component_status=component_status,
            payload=payload,
        )


def validate_event_sequence(events: tuple[TraceEvent, ...]) -> None:
    """Reject broken order, impossible causality, and false restored completion."""

    if not events:
        raise ValueError("trace must contain events")
    run_id = events[0].run_id
    if events[0].event_type != "run_started":
        raise ValueError("trace must begin with run_started")
    options: dict[str, tuple[str, ...]] = {}
    requests: set[str] = set()
    request_labels: dict[str, tuple[str, ...]] = {}
    model_choices: dict[str, str] = {}
    effective_choices: dict[str, str] = {}
    tools: set[str] = set()
    proposals: set[str] = set()
    passing_final: dict[str, set[str]] = {}
    committed: set[str] = set()
    causes: set[str] = set()
    passing_checks: dict[str, str] = {}
    explanations: set[str] = set()
    previous_logical_time = -1
    for expected_sequence, event in enumerate(events):
        if event.run_id != run_id or event.sequence != expected_sequence:
            raise ValueError("trace run IDs and sequences must be contiguous")
        if event.logical_time < previous_logical_time:
            raise ValueError("trace logical time must be monotonic")
        previous_logical_time = event.logical_time
        payload = event.payload
        _validate_decider_wire_event(event.event_type, payload)
        if event.event_type == "options_filtered":
            options[payload["decision_id"]] = tuple(payload["eligible_labels"])
        elif event.event_type == "decider_request":
            decision_id = payload["decision_id"]
            requests.add(decision_id)
            question = payload["request"].get("questions", {}).get("next_recovery_step", {})
            criteria = question.get("criteria")
            if isinstance(criteria, dict):
                labels = tuple(criteria)
                request_labels[decision_id] = labels
                if decision_id in options and set(labels) != set(options[decision_id]):
                    raise ValueError("Decider request choices do not match filtered options")
        elif event.event_type == "decider_response":
            decision_id = payload["decision_id"]
            if decision_id not in requests:
                raise ValueError("Decider response has no request")
            model_choice = payload["model_choice"]
            if decision_id in request_labels and model_choice not in request_labels[decision_id]:
                raise ValueError("Decider response choice was not requested")
            model_choices[decision_id] = model_choice
        elif event.event_type == "decision_policy_applied":
            decision_id = payload["decision_id"]
            model_choice = payload["model_choice"]
            if decision_id in requests:
                if model_choices.get(decision_id) != model_choice:
                    raise ValueError("decision policy model choice does not match response")
            elif model_choice is not None:
                raise ValueError("local no-decision policy cannot claim a model choice")
            if (
                model_choice is None
                and payload["override_reason"] != "INSUFFICIENT_CHOICE_CARDINALITY"
            ):
                raise ValueError("local no-decision policy requires a cardinality reason")
            effective = payload["effective_choice"]
            if decision_id in options and effective not in options[decision_id]:
                raise ValueError("effective choice is not filtered and eligible")
            effective_choices[decision_id] = effective
        elif event.event_type == "tool_dispatch_started":
            decision_id = payload["decision_id"]
            action = payload["action"]
            if effective_choices.get(decision_id) != action:
                raise ValueError("tool dispatch does not match effective decision")
            if payload["tool_name"] != TOOL_NAME_BY_ACTION[Action(action)]:
                raise ValueError("tool name does not match the authoritative action mapping")
            tools.add(payload["tool_call_id"])
            causes.add(payload["tool_call_id"])
        elif event.event_type == "tool_dispatch_finished":
            if payload["tool_call_id"] not in tools:
                raise ValueError("tool result has no matching dispatch start")
        elif event.event_type == "proposal_prepared":
            if payload["tool_call_id"] not in tools:
                raise ValueError("proposal has no matching tool call")
            proposals.add(payload["proposal_id"])
        elif event.event_type == "gate_evaluated":
            if payload["proposal_id"] not in proposals:
                raise ValueError("gate has no proposal")
            if payload["phase"] == "FINAL" and payload["passed"]:
                passing_final.setdefault(payload["proposal_id"], set()).add(payload["gate"])
        elif event.event_type == "approval_consumed":
            proposal_id = payload["proposal_id"]
            if len(passing_final.get(proposal_id, set())) != 5:
                raise ValueError("commit requires all five passing final gates")
            committed.add(payload["transition_id"])
            causes.add(payload["transition_id"])
        elif event.event_type == "transition_changed":
            if payload["transition_id"] not in committed:
                raise ValueError("transition has no atomic commit")
        elif event.event_type in {"registration_check", "telemetry_check"}:
            if payload["cause_id"] not in causes:
                raise ValueError("layer check has no state-changing cause")
            if payload["passed"]:
                passing_checks[payload["check_id"]] = event.event_type
        elif event.event_type == "bedrock_request":
            explanations.add(payload["explanation_id"])
        elif event.event_type in {"bedrock_result", "bedrock_unavailable"}:
            if payload["explanation_id"] not in explanations:
                raise ValueError("Bedrock outcome has no request")
        elif event.event_type == "run_completed" and payload["final_status"] == "RESTORED":
            registration = payload["latest_registration_check_id"]
            telemetry = payload["latest_telemetry_check_id"]
            if (
                passing_checks.get(registration) != "registration_check"
                or passing_checks.get(telemetry) != "telemetry_check"
            ):
                raise ValueError("RESTORED requires distinct passing layer checks")
    terminal = events[-1]
    if explanations and not terminal.payload.get("explainer_invoked", False):
        raise ValueError("terminal event must record the observed Bedrock invocation")
    blocked_indexes = [
        index for index, event in enumerate(events) if event.event_type == "proposal_blocked"
    ]
    if blocked_indexes:
        blocked_index = blocked_indexes[-1]
        if not (
            blocked_index == len(events) - 2
            and events[-1].event_type == "run_escalated"
            and events[-1].payload["reason"] == "PROFILE_PROPOSAL_BLOCKED"
            and events[-1].payload["explainer_invoked"] is False
        ):
            raise ValueError("blocked profile proposal must terminate immediately")
