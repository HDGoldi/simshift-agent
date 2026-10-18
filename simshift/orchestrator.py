"""Bedrock runs the agent loop; Strands Decider 2B still picks every recovery tool.

The Bedrock agent sees exactly two tools and neither takes an argument:
  get_incident_state  -> the observable state (never the hidden cause)
  advance_recovery    -> one Incident.step(): policy -> Decider -> one gated tool on the twin
So Bedrock decides when to look and when to stop and writes the report, but it has no way to name a
recovery action, skip the policy gate, or approve a profile change. That split is enforced by the tool
surface, not by the prompt.

    python -m simshift.orchestrator BR_PROFILE --approve
"""
from __future__ import annotations

import argparse
import json
import os

from strands import Agent, tool
from strands.tools.executors import SequentialToolExecutor

from .agent import Incident, _print

SYSTEM_PROMPT = """You are SIMShift, a recovery agent for a SIMULATED cellular IoT fleet.

1. Call get_incident_state once.
2. Call advance_recovery. Each call runs ONE recovery step; a separate decision model chooses which tool
   runs, and you cannot choose or override it. Repeat until a result has "terminal": true.
3. Write a report for a fleet operations engineer, under 200 words, with these headings:
   What happened / Decisions (per step: options removed by policy, the choice, its confidence, the route) /
   Outcome (rates after the last step, restored or not, any profile change and its approval) / Next.

Quote numbers only from tool results; never invent measurements. Everything is simulated; say so once."""


def _summary(t: dict, inc: Incident) -> dict:
    d = t["decision"] or {}
    raw = d.get("raw") or {}
    return {"step": t["step"], "excluded_by_policy": d.get("excluded"), "decider_choice": raw.get("choice"),
            "probabilities": raw.get("probabilities"), "confidence": raw.get("confidence"),
            "route": d.get("route"), "route_reason": d.get("reason"), "note": t.get("note"), "tool_run": t["tool"],
            "tool_status": t["tool_status"], "tool_result": t["tool_result"], "rates_after": t["rates_after"],
            "terminal": inc.done}


def orchestrator_tools(inc: Incident) -> list:
    @tool
    def get_incident_state() -> str:
        """Return the current observable state of the simulated incident cohort as JSON."""
        return json.dumps(inc.twin.observe())

    @tool
    def advance_recovery() -> str:
        """Run ONE recovery step. A policy removes inadmissible options, a decision model picks the next tool,
        and that tool runs on the simulated fleet. Returns the decision, the tool result and the new rates."""
        if inc.done:
            return json.dumps({"error": "incident finished; write the report now", "terminal": True})
        return json.dumps(_summary(inc.step(), inc))

    return [get_incident_state, advance_recovery]


def orchestrate(scenario_id: str, approve: bool = False, decider=None, model=None) -> dict:
    inc = Incident(scenario_id, approve, decider, use_bedrock=True)
    agent = Agent(model=model or inc.llm, tools=orchestrator_tools(inc), system_prompt=SYSTEM_PROMPT,
                  tool_executor=SequentialToolExecutor(), callback_handler=None)  # steps never run concurrently
    reply = agent(f"New incident: {inc.twin.s['incident']}. Follow your procedure.")
    while not inc.done:  # Bedrock stopped early: finish deterministically (advance_calls < steps shows it)
        inc.step()
    usage = reply.metrics.accumulated_usage
    res = inc.result(explain=False)
    return {**res, "mode": "orchestrated", "report": str(reply).strip(),
            "bedrock_usage": {k: usage.get(k) for k in ("inputTokens", "outputTokens", "totalTokens")},
            "advance_calls": sum(m["role"] == "assistant" and any(c.get("toolUse", {}).get("name") == "advance_recovery"
                                                                for c in m["content"]) for m in agent.messages)}


if __name__ == "__main__":
    from patterns.capability_aware_router.router import DeciderClient

    from .agent import SCENARIOS
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario", choices=list(SCENARIOS))
    ap.add_argument("--approve", action="store_true", help="operator pre-approves a profile switch if one is proposed")
    ap.add_argument("--out", help="write full JSON trace here")
    a = ap.parse_args()
    url = os.environ.get("DECIDER_URL", "http://127.0.0.1:8099")
    res = orchestrate(a.scenario, a.approve, DeciderClient(url))
    res["decider_source"] = f"live {url}"
    _print(res, res["decider_source"])
    print(f"\nBedrock report ({res['bedrock_model']}, {res['advance_calls']} advance_recovery calls, "
          f"{res['bedrock_usage']}):\n{res['report']}")
    if a.out:
        os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
        with open(a.out + ".tmp", "w") as f:
            json.dump(res, f, indent=1)
        os.replace(a.out + ".tmp", a.out)
