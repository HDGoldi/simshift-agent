from conftest import OPTIONS, POLICY, FakeDecider

from patterns.capability_aware_router import CapabilityAwareRouter


def test_low_confidence_without_fallback_runs_nothing():
    r = CapabilityAwareRouter("q", OPTIONS, POLICY, FakeDecider("a", 0.2), low_confidence=0.5).step({})
    assert r.outcome == "low_confidence" and r.executed is None
    assert r.decision.choice == "a"  # the model's answer is still recorded


def test_low_confidence_uses_allowed_fallback():
    r = CapabilityAwareRouter(
        "q", OPTIONS, POLICY, FakeDecider("a", 0.2), low_confidence=0.5, fallback="safe"
    ).step({})
    assert r.outcome == "low_confidence_fallback" and r.executed == "safe"


def test_confident_choice_runs():
    r = CapabilityAwareRouter("q", OPTIONS, POLICY, FakeDecider("a", 0.8), low_confidence=0.5).step({})
    assert r.outcome == "executed" and r.executed == "a"
