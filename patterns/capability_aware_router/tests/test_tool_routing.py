from conftest import OPTIONS, POLICY, FakeDecider

from patterns.capability_aware_router import CapabilityAwareRouter


def test_choice_selects_the_tool_that_runs():
    """Flip the model's choice -> a different tool runs. The model's answer is causal."""
    seen = set()
    for c in ("a", "b", "safe"):
        r = CapabilityAwareRouter("q", OPTIONS, POLICY, FakeDecider(c)).step({})
        assert r.outcome == "executed"
        assert r.executed == c and r.tool_output == c and r.tool_name == f"tool_{c}"
        seen.add(r.tool_name)
    assert len(seen) == 3


def test_trace_links_decision_to_tool():
    r = CapabilityAwareRouter("q", OPTIONS, POLICY, FakeDecider("a")).step({})
    t = r.to_trace()
    assert t["choice"] == "a" and t["executed"] == "a" and t["tool"] == "tool_a"
    assert t["question"] == "q" and t["model"] == "fake"
