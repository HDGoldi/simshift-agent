from strands import Agent
from strands.models import BedrockModel
from patterns.capability_aware_router.router import CapabilityAwareRouter
from patterns.capability_aware_router.tests.helpers import FakeDecider, ran, OPTIONS, TOOLS, do_a, hold


def test_forbidden_action_denied_even_on_direct_call():
    r = CapabilityAwareRouter(decider=FakeDecider("a"), instructions="?", options=OPTIONS, tools=TOOLS,
                              policy=lambda s: {"a": "forbidden"}, fallback="hold")
    agent = Agent(model=BedrockModel(model_id="unused", region_name="us-east-1"), tools=[do_a, hold],
                  interventions=[r.gate(lambda: {})], callback_handler=None)
    ran.clear()
    res = agent.tool.do_a()
    assert res["status"] == "error" and "forbidden" in res["content"][0]["text"] and ran == []
