from patterns.capability_aware_router.tests.helpers import FakeDecider, setup


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


def test_inconsistent_answer_fails_closed():
    for probs, conf in (({"a": 0.9, "b": 0.05, "look": 0.05, "hold": 0.05}, None),  # sums to 1.05
                        ({"a": 0.2, "b": 0.6, "look": 0.1, "hold": 0.1}, None),  # choice is not the argmax
                        ({"a": 0.7, "b": 0.1, "look": 0.1, "hold": 0.1}, 0.99),  # confidence not derived
                        ({"a": 0.7, "b": 0.3}, None)):  # options missing
        r, agent, seen = setup(FakeDecider("a", probs, conf))
        d, _ = r.step(agent, {})
        assert (d.selected, d.route, seen) == ("hold", "fallback", ["hold"]) and "inconsistent" in d.reason, probs
