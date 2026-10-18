# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

"""Pure profile gates and one lock-protected atomic commit."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal

from simshift.domain.enums import GateName, GateReason, ProfileState, RiskClass, TransitionState
from simshift.domain.models import (
    ApprovalGrant,
    BlockedProposalAudit,
    GateResult,
    ObservableIncident,
    PolicyMetadata,
    ProfileTransitionProposal,
    TransitionRecord,
)
from simshift.scenarios.repository import IncidentRuntime

GATE_POLICY_VERSION = "profile-gates-v1"


def proposal_id_for(
    run_id: str, tool_call_id: str, source_profile_id: str, target_profile_id: str
) -> str:
    raw = f"proposal\0{run_id}\0{tool_call_id}\0{source_profile_id}\0{target_profile_id}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def transition_id_for(run_id: str, proposal_id: str) -> str:
    return hashlib.sha256(f"transition\0{run_id}\0{proposal_id}".encode()).hexdigest()[:32]


def approval_id_for(
    *,
    run_id: str,
    proposal_id: str,
    incident_id: str,
    source_profile_id: str,
    target_profile_id: str,
    status: str,
) -> str:
    raw = (
        f"approval\0{run_id}\0{proposal_id}\0{incident_id}\0"
        f"{source_profile_id}\0{target_profile_id}\0{status}"
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def prepare_profile_transition(
    observable: ObservableIncident,
    policy: PolicyMetadata,
    *,
    run_id: str,
    tool_call_id: str,
) -> ProfileTransitionProposal:
    """Choose the first eligible disabled target and return a proposal, never a command."""

    candidates = sorted(
        (
            profile
            for profile in policy.profiles
            if profile.state is ProfileState.INSTALLED_DISABLED
            and profile.owner_id == policy.owner_id
            and profile.target_eligible
        ),
        key=lambda profile: profile.profile_id,
    )
    if not candidates:
        raise ValueError("no eligible installed-disabled profile target")
    target = candidates[0]
    prepared_revision = observable.observation_revision + 1
    return ProfileTransitionProposal(
        proposal_id=proposal_id_for(
            run_id, tool_call_id, observable.active_profile_id, target.profile_id
        ),
        run_id=run_id,
        tool_call_id=tool_call_id,
        incident_id=observable.incident_id,
        basis_observation_revision=observable.observation_revision,
        prepared_observation_revision=prepared_revision,
        source_profile_id=observable.active_profile_id,
        target_profile_id=target.profile_id,
    )


def materialize_approval(proposal: ProfileTransitionProposal, *, granted: bool) -> ApprovalGrant:
    """Create scripted simulated intent bound to every proposal identity field."""

    status: Literal["GRANTED", "DENIED"] = "GRANTED" if granted else "DENIED"
    approval_id = approval_id_for(
        run_id=proposal.run_id,
        proposal_id=proposal.proposal_id,
        incident_id=proposal.incident_id.value,
        source_profile_id=proposal.source_profile_id,
        target_profile_id=proposal.target_profile_id,
        status=status,
    )
    return ApprovalGrant(
        approval_id=approval_id,
        run_id=proposal.run_id,
        proposal_id=proposal.proposal_id,
        incident_id=proposal.incident_id,
        source_profile_id=proposal.source_profile_id,
        target_profile_id=proposal.target_profile_id,
        status=status,
    )


class ProfileTransitionPolicy:
    """Evaluate all five gates without mutating input state."""

    @staticmethod
    def evaluate(
        observable: ObservableIncident,
        policy: PolicyMetadata,
        proposal: ProfileTransitionProposal,
        approval: ApprovalGrant | None,
        transition_id: str,
    ) -> tuple[GateResult, ...]:
        profiles = {profile.profile_id: profile for profile in policy.profiles}
        source = profiles.get(proposal.source_profile_id)
        target = profiles.get(proposal.target_profile_id)
        enabled = [profile for profile in policy.profiles if profile.state is ProfileState.ENABLED]

        capability = GateReason.PASS
        if not policy.transition_supported:
            capability = GateReason.TRANSITION_UNSUPPORTED
        elif (
            len(enabled) != 1
            or source is None
            or source.state is not ProfileState.ENABLED
            or observable.active_profile_id != proposal.source_profile_id
        ):
            capability = GateReason.ACTIVE_PROFILE_INVARIANT
        elif (
            target is None
            or target.state is not ProfileState.INSTALLED_DISABLED
            or target.profile_id == proposal.source_profile_id
        ):
            capability = GateReason.TARGET_NOT_INSTALLED_DISABLED
        elif not policy.ipa_available:
            capability = GateReason.IPA_UNAVAILABLE

        reachability = GateReason.PASS
        if not policy.management.reachable:
            reachability = GateReason.MANAGEMENT_UNREACHABLE
        elif not policy.eim_associated:
            reachability = GateReason.EIM_NOT_ASSOCIATED
        elif policy.management.age_seconds > policy.management.max_age_seconds:
            reachability = GateReason.MANAGEMENT_STALE

        authorization = GateReason.PASS
        if not policy.owner_authorized:
            authorization = GateReason.OWNER_NOT_AUTHORIZED
        elif target is None or target.owner_id != policy.owner_id:
            authorization = GateReason.TARGET_OWNER_MISMATCH

        approval_reason = GateReason.PASS
        if approval is None or approval.status != "GRANTED":
            approval_reason = GateReason.APPROVAL_REQUIRED
        else:
            expected_id = approval_id_for(
                run_id=approval.run_id,
                proposal_id=approval.proposal_id,
                incident_id=approval.incident_id.value,
                source_profile_id=approval.source_profile_id,
                target_profile_id=approval.target_profile_id,
                status=approval.status,
            )
            bindings_match = (
                approval.run_id == proposal.run_id
                and approval.proposal_id == proposal.proposal_id
                and approval.incident_id is proposal.incident_id
                and approval.source_profile_id == proposal.source_profile_id
                and approval.target_profile_id == proposal.target_profile_id
                and approval.approval_id == expected_id
            )
            if not bindings_match:
                approval_reason = GateReason.APPROVAL_BINDING_MISMATCH
            elif observable.observation_revision != proposal.prepared_observation_revision:
                approval_reason = GateReason.APPROVAL_STALE
            elif approval.approval_id in policy.consumed_approval_ids:
                approval_reason = GateReason.APPROVAL_ALREADY_CONSUMED

        risk = GateReason.PASS
        if policy.in_flight_transition_id is not None:
            risk = GateReason.TRANSITION_IN_FLIGHT
        elif observable.transition_count >= policy.max_transitions:
            risk = GateReason.TRANSITION_LIMIT_REACHED
        elif target is None or not target.target_eligible:
            risk = GateReason.TARGET_INELIGIBLE
        elif target.risk_class is RiskClass.HIGH:
            risk = GateReason.TARGET_RISK_HIGH
        elif transition_id in policy.used_transition_ids:
            risk = GateReason.IDEMPOTENCY_KEY_USED

        reasons = (capability, reachability, authorization, approval_reason, risk)
        return tuple(
            GateResult(
                gate=gate,
                passed=reason is GateReason.PASS,
                reason=reason,
                detail="gate passed" if reason is GateReason.PASS else reason.value,
            )
            for gate, reason in zip(GateName, reasons, strict=True)
        )


@dataclass(frozen=True)
class CommitResult:
    preview: tuple[GateResult, ...]
    final: tuple[GateResult, ...]
    outcome: TransitionRecord | BlockedProposalAudit
    duplicate: bool


class TransitionCoordinator:
    """Recheck under the incident lock and commit all-or-nothing."""

    def __init__(self, runtime: IncidentRuntime) -> None:
        self.runtime = runtime

    def commit(
        self,
        proposal: ProfileTransitionProposal,
        approval: ApprovalGrant | None,
    ) -> CommitResult:
        transition_id = transition_id_for(proposal.run_id, proposal.proposal_id)
        preview = ProfileTransitionPolicy.evaluate(
            self.runtime.observable,
            self.runtime.policy,
            proposal,
            approval,
            transition_id,
        )
        with self.runtime.lock:
            existing_audit = self.runtime.audits.get(proposal.proposal_id)
            if existing_audit is not None:
                return CommitResult(
                    preview, existing_audit.final_gate_results, existing_audit, True
                )
            existing_record = next(
                (
                    record
                    for record in self.runtime.transitions.values()
                    if record.proposal_id == proposal.proposal_id
                    or record.transition_id == transition_id
                ),
                None,
            )
            if existing_record is not None:
                return CommitResult(
                    preview, preview, existing_record.model_copy(update={"duplicate": True}), True
                )

            final = ProfileTransitionPolicy.evaluate(
                self.runtime.observable,
                self.runtime.policy,
                proposal,
                approval,
                transition_id,
            )
            if not all(result.passed for result in final):
                audit = BlockedProposalAudit(
                    proposal_id=proposal.proposal_id,
                    status="BLOCKED",
                    source_profile_id=proposal.source_profile_id,
                    target_profile_id=proposal.target_profile_id,
                    final_gate_results=final,
                    command_created=False,
                    approval_consumed=False,
                )
                self.runtime.audits[proposal.proposal_id] = audit
                return CommitResult(preview, final, audit, False)

            if approval is None:  # all approval gates passing makes this unreachable
                raise RuntimeError("passing commit has no approval")
            new_policy = self.runtime.policy.model_copy(
                update={
                    "in_flight_transition_id": transition_id,
                    "used_transition_ids": self.runtime.policy.used_transition_ids
                    + (transition_id,),
                    "consumed_approval_ids": self.runtime.policy.consumed_approval_ids
                    + (approval.approval_id,),
                }
            )
            new_observable = self.runtime.observable.model_copy(
                update={"transition_count": self.runtime.observable.transition_count + 1}
            )
            record = TransitionRecord(
                transition_id=transition_id,
                proposal_id=proposal.proposal_id,
                run_id=proposal.run_id,
                tool_call_id=proposal.tool_call_id,
                source_profile_id=proposal.source_profile_id,
                target_profile_id=proposal.target_profile_id,
                approval_id=approval.approval_id,
                states=(
                    TransitionState.REQUESTED,
                    TransitionState.VALIDATED,
                    TransitionState.APPROVED,
                ),
                terminal=False,
                duplicate=False,
            )
            self.runtime.policy = new_policy
            self.runtime.observable = new_observable
            self.runtime.transitions[transition_id] = record
            return CommitResult(preview, final, record, False)
