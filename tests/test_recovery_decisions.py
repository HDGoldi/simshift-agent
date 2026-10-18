"""SIMShift-level tests: policy rules, causal routing, no hidden-truth leakage, live model check."""

from __future__ import annotations

import pytest

from decider.recovery_decisions import OPTIONS, build_router
from patterns.capability_aware_router import Decision, HttpDeciderClient, NonAdmissibleChoice
from simulator import scenarios


class FakeDecider:
    def __init__(self, choice=None):
        self.choice, self.offered, self.state_seen = choice, [], None

    def choose(self, state, question, criteria):
        self.offered, self.state_seen = list(criteria), state
        c = self.choice or self.offered[0]
        return Decision(choice=c, probabilities={c: 1.0}, confidence=1.0, model="fake")


def test_decider_controls_tool():
    state = scenarios.observe("profile_recovery")
    allowed, _ = build_router(FakeDecider()).admissible(state)
    ran = {build_router(FakeDecider(c)).step(state).tool_name for c in allowed}
    by_name = {o.name: o.tool.__name__ for o in OPTIONS}
    assert ran == {by_name[c] for c in allowed} and len(ran) > 1


def test_policy_filters_unavailable_operator():
    _, removed = build_router(FakeDecider()).admissible(scenarios.observe("profile_recovery"))
    assert removed["try_allowed_operator"] == "no permitted alternate operator on the active profile"


def test_unreachable_blocks_profile_change():
    state = scenarios.observe("unreachable_device")
    allowed, removed = build_router(FakeDecider()).admissible(state)
    assert "evaluate_profile_change" not in allowed
    assert removed["evaluate_profile_change"] == "no reachable management path"
    assert len(allowed) >= 2, "Decider must have a real choice, not a single option"
    with pytest.raises(NonAdmissibleChoice):
        build_router(FakeDecider("evaluate_profile_change")).step(state)


@pytest.mark.parametrize("name", scenarios.names())
def test_no_truth_leakage(name):
    d = FakeDecider()
    build_router(d).step(scenarios.observe(name))
    hidden = scenarios.load(name)["evaluator_only"]
    assert hidden["true_cause"] not in d.state_seen
    assert "evaluator_only" not in scenarios.observe(name)


def _server_up() -> bool:
    try:
        HttpDeciderClient().health()
        return True
    except OSError:
        return False


@pytest.mark.live
@pytest.mark.skipif(not _server_up(), reason="no local strands-decider server")
def test_decider_is_real():
    r = build_router(HttpDeciderClient()).step(scenarios.observe("profile_recovery"))
    assert r.decision.model.startswith("strands-decider-2B")
    assert r.decision.choice in r.allowed
    assert abs(sum(r.decision.probabilities.values()) - 1.0) < 1e-3
