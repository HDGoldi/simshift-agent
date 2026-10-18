from patterns.capability_aware_router.tests.helpers import FakeDecider, setup, ran


def test_tool_routing_follows_decider_choice():
    for choice, tool_name in (("a", "do_a"), ("b", "do_b")):
        r, agent, seen = setup(FakeDecider(choice))
        d, res = r.step(agent, {"x": 1})
        assert d.route == "act" and seen == ran == [tool_name] and res["status"] == "success"
