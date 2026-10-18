# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

from simshift.policy.profile_transition import TransitionCoordinator
from simshift.simulator.euicc import VirtualEuiccEngine


def test_duplicate_dispatch_has_no_second_effect(approved_br) -> None:
    runtime, proposal, approval = approved_br
    transition = TransitionCoordinator(runtime).commit(proposal, approval).outcome
    engine = VirtualEuiccEngine(runtime)
    first = engine.dispatch(transition.transition_id)  # type: ignore[union-attr]
    observable = runtime.observable
    second = engine.dispatch(transition.transition_id)  # type: ignore[union-attr]
    assert first.duplicate_suppressed is False
    assert second.duplicate_suppressed is True
    assert second.transition.duplicate is True
    assert second.registration is second.telemetry is None
    assert runtime.observable == observable
