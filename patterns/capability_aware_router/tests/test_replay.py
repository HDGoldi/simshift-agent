from patterns.capability_aware_router.tests.helpers import FakeDecider, setup


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
