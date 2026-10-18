from patterns.capability_aware_router.tests.helpers import FakeDecider, setup


def test_capability_filter_never_offers_excluded_option():
    dec = FakeDecider("a")
    r, agent, _ = setup(dec, policy=lambda s: {"b": "not allowed here"})
    d = r.decide({})
    assert "b" not in dec.calls[0]["options"] and d.excluded == {"b": "not allowed here"}


def test_only_fallback_admissible_skips_model_call():
    dec = FakeDecider("a")
    r, _, _ = setup(dec, policy=lambda s: {"a": "x", "b": "x", "look": "x"})
    assert r.decide({}).selected == "hold" and dec.calls == []
