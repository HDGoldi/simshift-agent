"""Mechanical checks over saved run traces, so no published run can claim more than its own events show.

    python -m simshift.validate docs/sample-runs/*.json
"""
from __future__ import annotations

import json
import sys

from patterns.capability_aware_router.router import inconsistent

from .agent import TOOLS
from .policy import FALLBACK, OPTIONS, exclusions
from .simulator import RESTORED_THRESHOLD, SCENARIOS


def step_problems(t: dict, prev_gate: dict | None, hidden: str | None = None) -> list[str]:
    """Checks one recorded step. Also used on the benchmark rows, which keep only decision, tool and note."""
    out, d, at = [], t["decision"], f"step {t.get('step', '?')}"
    if d is None:  # no model decision: an escalation, or a human approving the proposal the previous step left
        approval = (t.get("note") or "").startswith("operator approved") and t["tool"] == TOOLS["evaluate_profile_change"]
        if t["tool"] != TOOLS["escalate_or_wait"] and not approval:
            out.append(f"{at}: a step without a decision must be an escalation or a human approval")
        if approval and not (prev_gate and prev_gate["failed"] == ["human_approval"]
                             and prev_gate["proposal_id"] in t["note"]):
            out.append(f"{at}: approval step does not answer a pending proposal from the previous step")
        return out
    excluded = {k: v for k, v in exclusions(d["state"]).items() if k != FALLBACK}
    if excluded != d["excluded"] or set(d["eligible"]) != set(OPTIONS) - set(excluded):
        out.append(f"{at}: recorded options differ from what the policy gives for the recorded state")
    if t["tool"] != TOOLS[d["selected"]] or d["selected"] not in d["eligible"]:
        out.append(f"{at}: executed tool {t['tool']} is not the routed admissible option {d['selected']}")
    raw = d["raw"] or {}
    if "choice" in raw:
        if d["route"] == "act" and d["selected"] != raw["choice"]:
            out.append(f"{at}: route act but the selected option is not the Decider choice")
        if raw["choice"] in d["eligible"] and (bad := inconsistent(raw, d["eligible"])):
            out.append(f"{at}: recorded Decider answer is inconsistent: {bad}")
    if hidden and hidden in json.dumps(d["state"]):
        out.append(f"{at}: hidden cause leaked into the state sent to Decider")
    return out


def _gate(t: dict) -> dict | None:
    return t["tool_result"].get("gate") if isinstance(t.get("tool_result"), dict) else None


def problems(run: dict) -> list[str]:
    out, prev_gate, allowed_gates = [], None, 0
    hidden = SCENARIOS[run["scenario"]]["hidden"]["cause"]
    for t in run["trace"]:
        out += step_problems(t, prev_gate, hidden)
        prev_gate = _gate(t)
        allowed_gates += bool(prev_gate and prev_gate["allowed"])
    enables = sum(e["kind"] == "eim_enable_profile" and e.get("ok") for e in run["events"])
    if enables > allowed_gates:
        out.append(f"{enables} profile enables but only {allowed_gates} passing gates")
    o = run["outcome"]
    if o.get("forbidden_executions"):
        out.append(f"{o['forbidden_executions']} forbidden executions recorded")
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
