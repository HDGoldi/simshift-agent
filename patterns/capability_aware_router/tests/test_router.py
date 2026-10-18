"""Pattern tests. No model download, no AWS: a fake Decider stands in for the HTTP client."""
from strands import Agent, tool
from strands.hooks import BeforeToolCallEvent
from strands.models import BedrockModel

from patterns.capability_aware_router.router import CapabilityAwareRouter


class FakeDecider:
    """Answers like the real model: confidence is derived from the probabilities unless overridden."""

    def __init__(self, choice, probs=None, confidence=None):
        self.choice, self.probs, self.confidence, self.calls = choice, probs, confidence, []

    def choose(self, state, instructions, options, name="next_tool"):
        self.calls.append({"state": state, "options": dict(options)})
        probs = self.probs or {o: (1.0 if o == self.choice else 0.0) for o in options}
        n = len(probs)
        conf = self.confidence if self.confidence is not None else (n * max(probs.values()) - 1) / (n - 1)
        return {"choice": self.choice, "probabilities": probs, "confidence": conf}


ran = []


@tool
def do_a() -> str:
    """Tool A."""
    ran.append("do_a"); return "a"


@tool
def do_b() -> str:
    """Tool B."""
    ran.append("do_b"); return "b"


@tool
def look() -> str:
    """Read-only tool."""
    ran.append("look"); return "seen"


@tool
def hold() -> str:
    """Fallback."""
    ran.append("hold"); return "held"


OPTIONS = {"a": "do A", "b": "do B", "look": "inspect", "hold": "hand off"}
TOOLS = {"a": "do_a", "b": "do_b", "look": "look", "hold": "hold"}


def setup(decider, policy=lambda s: {}):
    r = CapabilityAwareRouter(decider=decider, instructions="next?", options=OPTIONS, tools=TOOLS,
                              policy=policy, fallback="hold", read_only=frozenset({"look"}))
    agent = Agent(model=BedrockModel(model_id="unused", region_name="us-east-1"),
                  tools=[do_a, do_b, look, hold], interventions=[r.gate(lambda: {})], callback_handler=None)
    seen = []
    agent.add_hook(lambda e: seen.append(e.tool_use["name"]), BeforeToolCallEvent)
    ran.clear()
    return r, agent, seen


def test_tool_routing_follows_decider_choice():
    for choice, tool_name in (("a", "do_a"), ("b", "do_b")):
        r, agent, seen = setup(FakeDecider(choice))
        d, res = r.step(agent, {"x": 1})
        assert d.route == "act" and seen == ran == [tool_name] and res["status"] == "success"


def test_capability_filter_never_offers_excluded_option():
    dec = FakeDecider("a")
    r, agent, _ = setup(dec, policy=lambda s: {"b": "not allowed here"})
    d = r.decide({})
    assert "b" not in dec.calls[0]["options"] and d.excluded == {"b": "not allowed here"}


def test_low_confidence_gathers_evidence_then_falls_back():
    r, _, _ = setup(FakeDecider("a", {"a": 0.4, "b": 0.3, "look": 0.2, "hold": 0.1}))  # confidence 0.2
    assert r.decide({}).selected == "look"
    r, _, _ = setup(FakeDecider("a", {"a": 0.5, "b": 0.3, "hold": 0.2}),  # confidence 0.25
                    policy=lambda s: {"look": "already done"})
    d = r.decide({})
    assert (d.selected, d.route) == ("hold", "fallback") and "no read-only option" in d.reason


def test_inconsistent_answer_fails_closed():
    for probs, conf in (({"a": 0.9, "b": 0.05, "look": 0.05, "hold": 0.05}, None),  # sums to 1.05
                        ({"a": 0.2, "b": 0.6, "look": 0.1, "hold": 0.1}, None),  # choice is not the argmax
                        ({"a": 0.7, "b": 0.1, "look": 0.1, "hold": 0.1}, 0.99),  # confidence not derived
                        ({"a": 0.7, "b": 0.3}, None)):  # options missing
        r, agent, seen = setup(FakeDecider("a", probs, conf))
        d, _ = r.step(agent, {})
        assert (d.selected, d.route, seen) == ("hold", "fallback", ["hold"]) and "inconsistent" in d.reason, probs


def test_forbidden_action_denied_even_on_direct_call():
    r = CapabilityAwareRouter(decider=FakeDecider("a"), instructions="?", options=OPTIONS, tools=TOOLS,
                              policy=lambda s: {"a": "forbidden"}, fallback="hold")
    agent = Agent(model=BedrockModel(model_id="unused", region_name="us-east-1"), tools=[do_a, hold],
                  interventions=[r.gate(lambda: {})], callback_handler=None)
    ran.clear()
    res = agent.tool.do_a()
    assert res["status"] == "error" and "forbidden" in res["content"][0]["text"] and ran == []


def test_only_fallback_admissible_skips_model_call():
    dec = FakeDecider("a")
    r, _, _ = setup(dec, policy=lambda s: {"a": "x", "b": "x", "look": "x"})
    assert r.decide({}).selected == "hold" and dec.calls == []


def test_decider_failure_fails_closed():
    class Down:
        def choose(self, *a, **k):
            raise OSError("connection refused")
    r, agent, seen = setup(Down())
    d, res = r.step(agent, {})
    assert (d.selected, d.route) == ("hold", "fallback") and seen == ["hold"] and "connection refused" in d.raw["error"]


def test_non_admissible_choice_falls_back():
    dec = FakeDecider("b", {"a": 0.5, "look": 0.3, "hold": 0.2}, confidence=0.95)  # answers outside the menu
    r, agent, seen = setup(dec, policy=lambda s: {"b": "not allowed here"})
    d, _ = r.step(agent, {})
    assert (d.selected, d.route) == ("hold", "fallback") and seen == ["hold"] and "non-admissible" in d.reason


def test_malformed_answer_fails_closed():
    class Bad:
        def choose(self, *a, **k):
            return {"choice": "a", "probabilities": {}, "confidence": None}
    r, agent, seen = setup(Bad())
    d, _ = r.step(agent, {})
    assert (d.selected, d.route) == ("hold", "fallback") and seen == ["hold"] and "malformed" in d.raw["error"]


def test_replay_keeps_recorded_outages_in_order():
    from patterns.capability_aware_router.router import ReplayDecider

    class Flaky:
        def __init__(self):
            self.n = 0
        def choose(self, state, instructions, options, name="next_tool"):
            self.n += 1
            if self.n == 1:
                raise OSError("down")
            return {"choice": "a", "probabilities": {o: float(o == "a") for o in options}, "confidence": 1.0}
    recorder, _, _ = setup(Flaky())
    rec = [vars(recorder.decide({"t": i})) for i in (1, 2)]
    r, _, _ = setup(ReplayDecider(rec))
    assert [r.decide({"t": i}).route for i in (1, 2)] == [d["route"] for d in rec] == ["fallback", "act"]


def test_replay_refuses_a_different_question():
    from patterns.capability_aware_router.router import ReplayDecider
    recorder, _, _ = setup(FakeDecider("a"))
    rec = recorder.decide({"x": 1})
    r, _, _ = setup(ReplayDecider([vars(rec)]))
    assert r.decide({"x": 2}).route == "fallback"  # state changed: recorded answer not applied
    r, _, _ = setup(ReplayDecider([vars(rec)]))
    d = r.decide({"x": 1})
    assert (d.selected, d.route, d.raw["replayed"]) == ("a", "act", True)
