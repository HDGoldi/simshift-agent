# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

from simshift.domain.enums import ProfileState, TransitionState
from simshift.policy.profile_transition import TransitionCoordinator
from simshift.simulator.euicc import VirtualEuiccEngine


def test_approved_br_reaches_succeeded_after_both_checks(approved_br) -> None:
    runtime, proposal, approval = approved_br
    committed = TransitionCoordinator(runtime).commit(proposal, approval).outcome
    result = VirtualEuiccEngine(runtime).dispatch(committed.transition_id)  # type: ignore[union-attr]
    assert result.transition.states[-1] is TransitionState.SUCCEEDED
    assert result.recovery is not None and result.recovery.service_restored
    assert result.registration is not None and result.registration.passed
    assert result.telemetry is not None and result.telemetry.passed
    assert runtime.observable.active_profile_id == "profile_B"
    assert sum(profile.state is ProfileState.ENABLED for profile in runtime.policy.profiles) == 1
