# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

from simshift.domain.enums import GateReason
from simshift.policy.profile_transition import ProfileTransitionPolicy, transition_id_for


def _approval_reason(runtime, proposal, approval):
    results = ProfileTransitionPolicy.evaluate(
        runtime.observable,
        runtime.policy,
        proposal,
        approval,
        transition_id_for(proposal.run_id, proposal.proposal_id),
    )
    return results[3].reason


def test_every_binding_and_id_mismatch_denies(approved_br) -> None:
    runtime, proposal, approval = approved_br
    for updates in (
        {"run_id": "other"},
        {"proposal_id": "b" * 32},
        {"target_profile_id": "profile_C"},
        {"approval_id": "c" * 32},
    ):
        assert (
            _approval_reason(runtime, proposal, approval.model_copy(update=updates))
            is GateReason.APPROVAL_BINDING_MISMATCH
        )


def test_stale_and_consumed_approval_deny(approved_br) -> None:
    runtime, proposal, approval = approved_br
    runtime.observable = runtime.observable.model_copy(update={"observation_revision": 2})
    assert _approval_reason(runtime, proposal, approval) is GateReason.APPROVAL_STALE
    runtime.observable = runtime.observable.model_copy(update={"observation_revision": 1})
    runtime.policy = runtime.policy.model_copy(
        update={"consumed_approval_ids": (approval.approval_id,)}
    )
    assert _approval_reason(runtime, proposal, approval) is GateReason.APPROVAL_ALREADY_CONSUMED
