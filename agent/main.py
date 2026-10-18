"""Run SIMShift on the synthetic scenarios and append a JSONL trace.

    make serve-decider                              # in another terminal
    python -m agent.main                            # Decider + twin, all scenarios, no approvals
    python -m agent.main profile_recovery --approve # demo: approve profile changes the policy allows
    python -m agent.main --agent --approve          # full Strands agent: Bedrock + Decider + twin
    python -m agent.main --counterfactual application_failure evaluate_profile_change
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from agent.incident import Incident, deny_all
from patterns.capability_aware_router import HttpDeciderClient
from simulator import scenarios
from simulator.twin import replay

TRACE = Path(__file__).resolve().parent.parent / "logs" / "trace.jsonl"


def _ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _demo_approve(_twin, plan: str) -> bool:
    print(f"     APPROVAL GATE (demo flag): approved -> {plan}")
    return True


def _print_outcome(o: dict) -> None:
    print(f"  = restored={o['restored']} reg={o['registration_rate']} app={o['application_ack_rate']} "
          f"resolution={o['resolution']} downtime={o['downtime_minutes']}min "
          f"profile_changes={o['profile_changes']} unnecessary={o['unnecessary_profile_changes']} "
          f"blocked={o['blocked_actions']}")


def main(argv: list[str]) -> None:
    if "--counterfactual" in argv:
        _, name, *actions = argv
        print(json.dumps(replay(name, actions, approve=True), indent=2))
        return

    approve = _demo_approve if "--approve" in argv else deny_all
    names = [a for a in argv if not a.startswith("--")] or scenarios.names()
    decider = HttpDeciderClient()
    TRACE.parent.mkdir(exist_ok=True)

    with TRACE.open("a") as f:
        for name in names:
            if "--agent" in argv:
                from agent.bedrock import model_id
                from agent.recovery_agent import run

                out = dict(run(name, decider, approve=approve))
                out |= {"mode": "agent", "bedrock_model": model_id()}
            else:
                inc = Incident(name, decider, approve=approve)
                print(f"[{name}]")
                while not inc.done:
                    s = inc.step()
                    print(f"  step {len(inc.steps)}: removed={list(s['removed'])}")
                    print(f"    -> {s['choice']} conf={s['confidence']:.3f} "
                          f"({s['decider_latency_ms']:.0f} ms) | {s['tool_output']}")
                out = {"scenario": name, "mode": "router"} | inc.result()
            _print_outcome(out["outcome"])
            if "report" in out:
                print(out["report"])
            f.write(json.dumps({"ts": _ts()} | out, default=str) + "\n")


if __name__ == "__main__":
    main(sys.argv[1:])
