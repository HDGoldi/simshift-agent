"""Non-telecom example: pick the next remediation tool for a failing web service.

    strands-decider serve StrandsAgents/strands-decider-2B-qwen3.5-v1-2610 --device mlx --port 8099
    python -m patterns.capability_aware_router.example

No AWS needed: tools are invoked directly, so the Bedrock model object below is never called.
"""
import json

from strands import Agent, tool
from strands.models import BedrockModel

from patterns.capability_aware_router.router import CapabilityAwareRouter, DeciderClient

state = {"service": "checkout-api", "error_rate": 0.31, "p95_latency_ms": 4200, "deployed_minutes_ago": 12,
         "previous_release_available": True, "cpu_utilization": 0.35, "findings": []}


@tool
def rollback_release() -> str:
    """Roll back to the previous release."""
    return "rolled back to v41"


@tool
def scale_out() -> str:
    """Add replicas."""
    return "scaled 6 -> 12"


@tool
def inspect_logs() -> str:
    """Read-only: fetch recent error logs."""
    state["findings"].append("NullPointerException in PaymentClient since v42 deploy")
    return state["findings"][-1]


@tool
def page_oncall() -> str:
    """Hand off to a human."""
    return "paged on-call"


def policy(s: dict) -> dict[str, str]:
    out = {}
    if not s["previous_release_available"]:
        out["rollback_release"] = "no previous release to roll back to"
    if s["cpu_utilization"] < 0.6:
        out["scale_out"] = "CPU has headroom; more replicas cannot fix errors"
    if s["findings"]:
        out["inspect_logs"] = "logs already inspected"
    return out


router = CapabilityAwareRouter(
    decider=DeciderClient("http://127.0.0.1:8099"),
    instructions="Which next remediation step most safely restores the service?",
    options={"rollback_release": "Revert to the previous release; suits regressions after a recent deploy",
             "scale_out": "Add capacity; suits saturation",
             "inspect_logs": "Read-only: look at recent error logs",
             "page_oncall": "Hand off to a human"},
    tools={"rollback_release": "rollback_release", "scale_out": "scale_out",
           "inspect_logs": "inspect_logs", "page_oncall": "page_oncall"},
    policy=policy, fallback="page_oncall", read_only=frozenset({"inspect_logs"}))

agent = Agent(model=BedrockModel(region_name="us-east-1"), tools=[rollback_release, scale_out, inspect_logs, page_oncall],
              interventions=[router.gate(lambda: state)], callback_handler=None)

if __name__ == "__main__":
    for _ in range(3):
        d, res = router.step(agent, state)
        print(json.dumps({"excluded": d.excluded, "decider": d.raw, "route": d.route, "tool": d.tool,
                          "result": res["content"][0]["text"]}, indent=1))
        if d.selected in ("rollback_release", "page_oncall"):
            break
