# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

from simshift.domain.enums import GateName, GateReason
from simshift.policy.profile_transition import ProfileTransitionPolicy, transition_id_for


def test_all_five_br_gates_pass(approved_br) -> None:
    runtime, proposal, approval = approved_br
    results = ProfileTransitionPolicy.evaluate(
        runtime.observable,
        runtime.policy,
        proposal,
        approval,
        transition_id_for(proposal.run_id, proposal.proposal_id),
    )
    assert tuple(item.gate for item in results) == tuple(GateName)
    assert all(item.reason is GateReason.PASS for item in results)


def test_offline_reachability_gate_denies(prepared_br) -> None:
    runtime, proposal = prepared_br
    runtime.policy = runtime.policy.model_copy(
        update={"management": runtime.policy.management.model_copy(update={"reachable": False})}
    )
    results = ProfileTransitionPolicy.evaluate(
        runtime.observable,
        runtime.policy,
        proposal,
        None,
        transition_id_for(proposal.run_id, proposal.proposal_id),
    )
    assert results[1].reason is GateReason.MANAGEMENT_UNREACHABLE
    assert results[3].reason is GateReason.APPROVAL_REQUIRED
