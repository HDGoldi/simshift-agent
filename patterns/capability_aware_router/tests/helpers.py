"""Shared fakes for the pattern tests. No model download, no AWS: a fake Decider stands in for the HTTP client."""
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


