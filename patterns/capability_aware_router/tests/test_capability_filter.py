from conftest import OPTIONS, POLICY, FakeDecider

from patterns.capability_aware_router import CapabilityAwareRouter


def test_removed_options_are_never_offered():
    d = FakeDecider("a")
    r = CapabilityAwareRouter("q", OPTIONS, POLICY, d).step({"block_b": True})
    assert "b" not in d.offered
    assert r.removed == {"b": "b blocked by state"}


def test_nothing_allowed_runs_nothing_and_skips_model():
    d = FakeDecider("a")
    r = CapabilityAwareRouter("q", OPTIONS, POLICY, d).step({"block_all": True})
    assert r.outcome == "no_options" and r.executed is None and r.decision is None
    assert d.offered == []
