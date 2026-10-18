import pytest
from conftest import OPTIONS, POLICY, FakeDecider

from patterns.capability_aware_router import CapabilityAwareRouter, NonAdmissibleChoice


def test_non_admissible_choice_is_refused():
    with pytest.raises(NonAdmissibleChoice):
        CapabilityAwareRouter("q", OPTIONS, POLICY, FakeDecider("b")).step({"block_b": True})


def test_unknown_choice_is_refused():
    with pytest.raises(NonAdmissibleChoice):
        CapabilityAwareRouter("q", OPTIONS, POLICY, FakeDecider("delete_everything")).step({})


def test_risky_option_needs_approval():
    r = CapabilityAwareRouter("q", OPTIONS, POLICY, FakeDecider("c")).step({})
    assert r.outcome == "awaiting_approval" and r.executed is None


def test_risky_option_runs_when_approved():
    r = CapabilityAwareRouter("q", OPTIONS, POLICY, FakeDecider("c"), approve=lambda s, o: True).step({})
    assert r.outcome == "executed" and r.executed == "c"
