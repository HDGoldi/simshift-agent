from patterns.capability_aware_router.tests.helpers import FakeDecider, setup


def test_low_confidence_gathers_evidence_then_falls_back():
    r, _, _ = setup(FakeDecider("a", {"a": 0.4, "b": 0.3, "look": 0.2, "hold": 0.1}))  # confidence 0.2
    assert r.decide({}).selected == "look"
    r, _, _ = setup(FakeDecider("a", {"a": 0.5, "b": 0.3, "hold": 0.2}),  # confidence 0.25
                    policy=lambda s: {"look": "already done"})
    d = r.decide({})
    assert (d.selected, d.route) == ("hold", "fallback") and "no read-only option" in d.reason
