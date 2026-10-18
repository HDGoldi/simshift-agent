# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

"""Strict immutable DTOs for observable, policy, and simulator state."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from .enums import (
    Action,
    DeliveryOutcome,
    EvidenceCode,
    GateName,
    GateReason,
    HiddenCause,
    ManagementKind,
    ProfileState,
    Reachability,
    RegistrationStatus,
    RiskClass,
    ScenarioId,
    TelemetryStatus,
    TransitionState,
)

Token = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,32}$")]
OwnerId = Annotated[str, StringConstraints(pattern=r"^synthetic-[a-z0-9-]{1,32}$")]
HexId = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")]
CountryCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")]
Canary = Annotated[str, StringConstraints(pattern=r"^EVAL_ONLY_[A-Z0-9_]{8,48}$")]


class StrictFrozenModel(BaseModel):
    """Shared strict and finite configuration for domain records."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, allow_inf_nan=False)


class ObservableIncident(StrictFrozenModel):
    schema_version: Literal["1.0"]
    incident_id: ScenarioId
    observation_revision: int = Field(ge=0, le=64)
    country_code: CountryCode
    cohort_size: int = Field(ge=1, le=100_000)
    registration_status: RegistrationStatus
    attach_success_rate: float = Field(ge=0.0, le=1.0)
    telemetry_status: TelemetryStatus
    telemetry_ack_rate: float = Field(ge=0.0, le=1.0)
    active_profile_id: Token
    alternative_profile_installed: bool
    allowed_alternative_operator_available: bool
    management_reachability: Reachability
    ipa_available: bool
    eim_associated: bool
    recent_firmware_change: bool
    connection_retry_count: int = Field(ge=0, le=2)
    transition_count: int = Field(ge=0, le=1)
    action_counts: dict[Action, int]
    evidence: tuple[EvidenceCode, ...] = Field(max_length=20)

    @model_validator(mode="after")
    def validate_collections(self) -> ObservableIncident:
        if set(self.action_counts) != set(Action):
            raise ValueError("action_counts must contain exactly all six actions")
        if any(
            isinstance(count, bool) or not 0 <= count <= 4 for count in self.action_counts.values()
        ):
            raise ValueError("action counts must be integers in [0, 4]")
        if len(set(self.evidence)) != len(self.evidence):
            raise ValueError("evidence must be unique")
        return self


class ProfileRecord(StrictFrozenModel):
    profile_id: Token
    state: ProfileState
    owner_id: OwnerId
    allowed_operator_ids: tuple[Token, ...] = Field(min_length=1, max_length=8)
    target_eligible: bool
    risk_class: RiskClass

    @model_validator(mode="after")
    def validate_operators_unique(self) -> ProfileRecord:
        if len(set(self.allowed_operator_ids)) != len(self.allowed_operator_ids):
            raise ValueError("allowed operator IDs must be unique")
        return self


class OperatorRecord(StrictFrozenModel):
    operator_id: Token
    currently_selected: bool
    permitted_on_active_profile: bool
    available: bool


class ManagementChannel(StrictFrozenModel):
    kind: ManagementKind
    reachable: bool
    age_seconds: int = Field(ge=0, le=86_400)
    max_age_seconds: int = Field(ge=0, le=86_400)


class PolicyMetadata(StrictFrozenModel):
    owner_id: OwnerId
    profiles: tuple[ProfileRecord, ...] = Field(min_length=2, max_length=8)
    operators: tuple[OperatorRecord, ...] = Field(min_length=1, max_length=16)
    transition_supported: bool
    ipa_available: bool
    eim_associated: bool
    owner_authorized: bool
    management: ManagementChannel
    max_transitions: Literal[1]
    in_flight_transition_id: HexId | None
    used_transition_ids: tuple[HexId, ...]
    consumed_approval_ids: tuple[HexId, ...]
    registration_threshold: float = Field(ge=0.0, le=1.0)
    telemetry_threshold: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_unique_records(self) -> PolicyMetadata:
        profile_ids = [item.profile_id for item in self.profiles]
        operator_ids = [item.operator_id for item in self.operators]
        if len(set(profile_ids)) != len(profile_ids):
            raise ValueError("profile IDs must be unique")
        if len(set(operator_ids)) != len(operator_ids):
            raise ValueError("operator IDs must be unique")
        if len(set(self.used_transition_ids)) != len(self.used_transition_ids):
            raise ValueError("used transition IDs must be unique")
        if len(set(self.consumed_approval_ids)) != len(self.consumed_approval_ids):
            raise ValueError("consumed approval IDs must be unique")
        return self


class ActionEffect(StrictFrozenModel):
    action: Action
    occurrence: int = Field(ge=1, le=2)
    evidence_added: tuple[EvidenceCode, ...] = Field(max_length=4)
    registration_probability: float | None = Field(default=None, ge=0.0, le=1.0)
    telemetry_probability: float | None = Field(default=None, ge=0.0, le=1.0)
    delivery_outcome: DeliveryOutcome
    target_profile_id: Token | None

    @model_validator(mode="after")
    def validate_evidence_unique(self) -> ActionEffect:
        if len(set(self.evidence_added)) != len(self.evidence_added):
            raise ValueError("effect evidence must be unique")
        return self


class EvaluatorTruth(StrictFrozenModel):
    leakage_canary: Canary
    hidden_cause: HiddenCause
    acceptable_next_actions: tuple[Action, ...] = Field(min_length=1)
    effects: tuple[ActionEffect, ...]

    @model_validator(mode="after")
    def validate_unique_values(self) -> EvaluatorTruth:
        if len(set(self.acceptable_next_actions)) != len(self.acceptable_next_actions):
            raise ValueError("acceptable actions must be unique")
        keys = [(effect.action, effect.occurrence) for effect in self.effects]
        if len(set(keys)) != len(keys):
            raise ValueError("effect action/occurrence pairs must be unique")
        return self


class ScenarioFixtureEnvelope(StrictFrozenModel):
    schema_version: Literal["1.0"]
    fixture_revision: Annotated[str, StringConstraints(pattern=r"^[a-z0-9._-]{1,32}$")]
    scenario_id: ScenarioId
    default_seed: int = Field(ge=0, le=2**32 - 1)
    observable_initial_state: ObservableIncident
    policy_metadata: PolicyMetadata


class ApprovalGrant(StrictFrozenModel):
    approval_id: HexId
    run_id: str = Field(min_length=1, max_length=128)
    proposal_id: HexId
    incident_id: ScenarioId
    source_profile_id: Token
    target_profile_id: Token
    status: Literal["GRANTED", "DENIED"]


class ProfileTransitionProposal(StrictFrozenModel):
    proposal_id: HexId
    run_id: str = Field(min_length=1, max_length=128)
    tool_call_id: str = Field(min_length=1, max_length=128)
    incident_id: ScenarioId
    basis_observation_revision: int = Field(ge=0, le=64)
    prepared_observation_revision: int = Field(ge=0, le=64)
    source_profile_id: Token
    target_profile_id: Token


class GateResult(StrictFrozenModel):
    gate: GateName
    passed: bool
    reason: GateReason
    detail: str = Field(max_length=300)

    @model_validator(mode="after")
    def validate_consistency(self) -> GateResult:
        if self.passed != (self.reason is GateReason.PASS):
            raise ValueError("passed is true exactly for PASS")
        return self


class BlockedProposalAudit(StrictFrozenModel):
    proposal_id: HexId
    status: Literal["BLOCKED"]
    source_profile_id: Token
    target_profile_id: Token
    final_gate_results: tuple[GateResult, ...]
    command_created: Literal[False]
    approval_consumed: Literal[False]

    @model_validator(mode="after")
    def validate_gate_order(self) -> BlockedProposalAudit:
        expected = tuple(GateName)
        if tuple(result.gate for result in self.final_gate_results) != expected:
            raise ValueError("blocked audit must contain all five gates in enum order")
        return self


_VALID_TRANSITION_PATHS = (
    (TransitionState.REQUESTED, TransitionState.VALIDATED, TransitionState.APPROVED),
    (
        TransitionState.REQUESTED,
        TransitionState.VALIDATED,
        TransitionState.APPROVED,
        TransitionState.SENT,
    ),
    (
        TransitionState.REQUESTED,
        TransitionState.VALIDATED,
        TransitionState.APPROVED,
        TransitionState.SENT,
        TransitionState.TIMED_OUT,
    ),
    (
        TransitionState.REQUESTED,
        TransitionState.VALIDATED,
        TransitionState.APPROVED,
        TransitionState.SENT,
        TransitionState.FAILED,
    ),
    (
        TransitionState.REQUESTED,
        TransitionState.VALIDATED,
        TransitionState.APPROVED,
        TransitionState.SENT,
        TransitionState.ACKNOWLEDGED,
        TransitionState.ENABLED,
        TransitionState.VERIFYING,
        TransitionState.SUCCEEDED,
    ),
    (
        TransitionState.REQUESTED,
        TransitionState.VALIDATED,
        TransitionState.APPROVED,
        TransitionState.SENT,
        TransitionState.ACKNOWLEDGED,
        TransitionState.ENABLED,
        TransitionState.VERIFYING,
        TransitionState.FAILED,
    ),
)


class TransitionRecord(StrictFrozenModel):
    transition_id: HexId
    proposal_id: HexId
    run_id: str = Field(min_length=1, max_length=128)
    tool_call_id: str = Field(min_length=1, max_length=128)
    source_profile_id: Token
    target_profile_id: Token
    approval_id: HexId
    states: tuple[TransitionState, ...]
    terminal: bool
    duplicate: bool

    @model_validator(mode="after")
    def validate_path(self) -> TransitionRecord:
        if self.states not in _VALID_TRANSITION_PATHS:
            raise ValueError("invalid transition state path")
        terminal = self.states[-1] in {
            TransitionState.SUCCEEDED,
            TransitionState.TIMED_OUT,
            TransitionState.FAILED,
        }
        if terminal != self.terminal:
            raise ValueError("terminal flag must match final state")
        return self


class LayerCheck(StrictFrozenModel):
    check_id: str = Field(min_length=1, max_length=128)
    kind: Literal["REGISTRATION", "TELEMETRY"]
    passed_count: int = Field(ge=0)
    cohort_size: int = Field(ge=1, le=100_000)
    rate: float = Field(ge=0.0, le=1.0)
    threshold: float = Field(ge=0.0, le=1.0)
    passed: bool

    @model_validator(mode="after")
    def validate_derived_values(self) -> LayerCheck:
        if self.passed_count > self.cohort_size:
            raise ValueError("passed count exceeds cohort size")
        if self.rate != self.passed_count / self.cohort_size:
            raise ValueError("rate must equal passed_count/cohort_size")
        if self.passed != (self.rate >= self.threshold):
            raise ValueError("passed must reflect the configured threshold")
        return self
