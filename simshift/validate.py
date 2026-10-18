"""Mechanical checks over saved run traces, so no published run can claim more than its own events show.

    python -m simshift.validate docs/sample-runs/*.json
"""
from __future__ import annotations

import json
import sys

from patterns.capability_aware_router.router import inconsistent

from .agent import TOOLS
from .simulator import RESTORED_THRESHOLD, SCENARIOS


def problems(run: dict) -> list[str]:
    out = []
    hidden = SCENARIOS[run["scenario"]]["hidden"]["cause"]
    allowed_gates = 0
    for t in run["trace"]:
        d, at = t["decision"], f"step {t['step']}"
        if d is None:  # no model decision: step-limit or declined-approval escalation, or a human approval
            approval = t.get("note", "").startswith("operator approved") and t["tool"] == TOOLS["evaluate_profile_change"]
            if t["tool"] != TOOLS["escalate_or_wait"] and not approval:
                out.append(f"{at}: a step without a decision must be an escalation or a human approval")
            gate = t["tool_result"].get("gate") if isinstance(t["tool_result"], dict) else None
            allowed_gates += bool(gate and gate["allowed"])
            continue
        if t["tool"] != TOOLS[d["selected"]] or d["selected"] not in d["eligible"]:
            out.append(f"{at}: executed tool {t['tool']} is not the routed admissible option {d['selected']}")
        raw = d["raw"] or {}
        if "choice" in raw:
            if d["route"] == "act" and d["selected"] != raw["choice"]:
                out.append(f"{at}: route act but the selected option is not the Decider choice")
            if raw["choice"] in d["eligible"] and (bad := inconsistent(raw, d["eligible"])):
                out.append(f"{at}: recorded Decider answer is inconsistent: {bad}")
        if hidden in json.dumps(d["state"]):
            out.append(f"{at}: hidden cause leaked into the state sent to Decider")
        gate = t["tool_result"].get("gate") if isinstance(t["tool_result"], dict) else None
        allowed_gates += bool(gate and gate["allowed"])
    enables = sum(e["kind"] == "eim_enable_profile" and e.get("ok") for e in run["events"])
    if enables > allowed_gates:
        out.append(f"{enables} profile enables but only {allowed_gates} passing gates")
    o = run["outcome"]
    if o["restored"] and not (o["final_rates"]["attach_success_rate"] >= RESTORED_THRESHOLD
                              and o["final_rates"]["app_ack_rate"] >= RESTORED_THRESHOLD):
        out.append("claims restored without passing registration and telemetry rates")
    return out


if __name__ == "__main__":
    failed = False
    for path in sys.argv[1:]:
        with open(path) as f:
            found = problems(json.load(f))
        failed |= bool(found)
        print(f"{'FAIL' if found else 'ok  '} {path}" + "".join(f"\n     - {p}" for p in found))
    sys.exit(failed)
