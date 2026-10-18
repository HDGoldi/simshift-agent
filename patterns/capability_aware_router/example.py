"""Non-telecom example: route a cloud-ops incident with the Capability-Aware Router.

    strands-decider serve StrandsAgents/strands-decider-2B-qwen3.5-v1-2610 --port 8099
    python -m patterns.capability_aware_router.example

`--fake` runs without a model server (fixed answer), to show the wiring only.
"""

from __future__ import annotations

import json
import sys

from patterns.capability_aware_router import (
    CapabilityAwareRouter,
    Decision,
    HttpDeciderClient,
    Option,
    Rule,
    RulePolicy,
)


def restart_service(s):  return f"restarted {s['service']}"
def roll_back_deploy(s): return f"rolled back {s['service']} to {s['previous_version']}"
def read_logs(s):        return f"collected last 15 min of logs for {s['service']}"
def page_on_call(s):     return "paged on-call engineer"


OPTIONS = [
    Option("restart_service", "restart the failing service; fits crashes with no recent change", restart_service),
    Option("roll_back_deploy", "roll back to the previous version; fits errors that began right after a deploy", roll_back_deploy, risky=True),
    Option("read_logs", "read-only: collect recent logs to learn more", read_logs),
    Option("page_on_call", "hand the incident to a human", page_on_call),
]

POLICY = RulePolicy([
    Rule("roll_back_deploy", lambda s: s["previous_version"] is None, "no previous version to roll back to"),
    Rule("restart_service", lambda s: s["restarts_last_hour"] >= 3, "restart budget spent"),
])

STATE = {
    "service": "checkout-api",
    "error_rate": 0.31,
    "minutes_since_deploy": 4,
    "previous_version": "v412",
    "restarts_last_hour": 3,
}


class _Fake:
    def choose(self, state, question, criteria):
        c = next(iter(criteria))
        return Decision(choice=c, probabilities={c: 1.0}, confidence=1.0, model="fake")


def main() -> None:
    decider = _Fake() if "--fake" in sys.argv else HttpDeciderClient()
    router = CapabilityAwareRouter(
        question="Which next action most safely restores the service?",
        options=OPTIONS,
        policy=POLICY,
        decider=decider,
        describe=lambda s: (
            f"Service {s['service']} error rate {s['error_rate']:.0%}. "
            f"Deployed {s['minutes_since_deploy']} minutes ago. Restarts in last hour: {s['restarts_last_hour']}."
        ),
        low_confidence=0.3,
        fallback="read_logs",
        # demo approval gate: pass --approve to allow risky options. Replace with your own human check.
        approve=lambda s, o: "--approve" in sys.argv,
    )
    print(json.dumps(router.step(STATE).to_trace(), indent=2))


if __name__ == "__main__":
    main()
