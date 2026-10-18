# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

from concurrent.futures import ThreadPoolExecutor

from simshift.domain.models import BlockedProposalAudit, TransitionRecord
from simshift.policy.profile_transition import TransitionCoordinator


def test_denial_creates_only_audit_without_state_mutation(prepared_br) -> None:
    runtime, proposal = prepared_br
    observable, policy = runtime.observable, runtime.policy
    result = TransitionCoordinator(runtime).commit(proposal, None)
    assert isinstance(result.outcome, BlockedProposalAudit)
    assert runtime.observable == observable and runtime.policy == policy
    assert not runtime.transitions


def test_concurrent_duplicate_commit_occurs_once(approved_br) -> None:
    runtime, proposal, approval = approved_br
    coordinator = TransitionCoordinator(runtime)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: coordinator.commit(proposal, approval), range(2)))
    assert all(isinstance(result.outcome, TransitionRecord) for result in results)
    assert len(runtime.transitions) == 1
    assert sum(not result.duplicate for result in results) == 1
    assert runtime.policy.consumed_approval_ids == (approval.approval_id,)
