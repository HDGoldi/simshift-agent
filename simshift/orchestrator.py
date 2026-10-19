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

from strands import Agent, ToolContext, tool
from strands.tools.executors import SequentialToolExecutor

from .agent import MAX_STEPS, Incident, _print, write_trace

SYSTEM_PROMPT = """You are SIMShift, a recovery agent for a SIMULATED cellular IoT fleet.

1. Call get_incident_state once.
2. Call advance_recovery. Each call runs ONE recovery step; a separate decision model chooses which tool
   runs, and you cannot choose or override it. Repeat until a result has "terminal": true.
3. Write a report for a fleet operations engineer, under 200 words, with these headings:
   What happened / Decisions (per step: options removed by policy, the choice, its confidence, the route) /
   Outcome (rates after the last step, restored or not, any profile change and its approval) / Next.

Quote numbers only from tool results; never invent measurements. A profile switch whose path ends UNCONFIRMED
got no result from the device: call its state unconfirmed. Everything is simulated; say so once."""


def _summary(t: dict, inc: Incident) -> dict:
    d = t["decision"] or {}
    raw = d.get("raw") or {}
    return {"step": t["step"], "excluded_by_policy": d.get("excluded"), "decider_choice": raw.get("choice"),
            "probabilities": raw.get("probabilities"), "confidence": raw.get("confidence"),
            "route": d.get("route"), "route_reason": d.get("reason"), "note": t.get("note"), "tool_run": t["tool"],
            "tool_status": t["tool_status"], "tool_result": t["tool_result"], "rates_after": t["rates_after"],
            "terminal": inc.done}


MAX_TOOL_CALLS = 2 * MAX_STEPS + 4  # each step needs at most one look and one advance, plus slack


def orchestrator_tools(inc: Incident) -> list:
    calls = {"advance": 0, "total": 0}

    def over_budget(ctx: ToolContext) -> str | None:
        calls["total"] += 1
        if calls["total"] <= MAX_TOOL_CALLS:
            return None
        ctx.invocation_state.setdefault("request_state", {})["stop_event_loop"] = True  # a runaway loop ends here
        return json.dumps({"error": "tool budget exhausted; the incident is finished deterministically",
                           "terminal": True})

    @tool(context="tool_context")
    def get_incident_state(tool_context: ToolContext) -> str:
        """Return the current observable state of the simulated incident cohort as JSON."""
        return over_budget(tool_context) or json.dumps(inc.twin.observe())

    @tool(context="tool_context")
    def advance_recovery(tool_context: ToolContext) -> str:
        """Run ONE recovery step. A policy removes inadmissible options, a decision model picks the next tool,
        and that tool runs on the simulated fleet. Returns the decision, the tool result and the new rates."""
        if stop := over_budget(tool_context):
            return stop
        if inc.done:
            return json.dumps({"error": "incident finished; write the report now", "terminal": True})
        calls["advance"] += 1
        return json.dumps(_summary(inc.step(), inc))

    get_incident_state.calls = advance_recovery.calls = calls
    return [get_incident_state, advance_recovery]


def orchestrate(scenario_id: str, approve: bool = False, decider=None, model=None) -> dict:
    inc = Incident(scenario_id, approve, decider, use_bedrock=True)
    tools = orchestrator_tools(inc)
    agent = Agent(model=model or inc.llm, tools=tools, system_prompt=SYSTEM_PROMPT,
                  tool_executor=SequentialToolExecutor(), callback_handler=None)  # steps never run concurrently
    report, error, rewritten = None, None, False
    try:
        report = str(agent(f"New incident: {inc.twin.s['incident']}. Follow your procedure.")).strip()
        if tools[0].calls["total"] > MAX_TOOL_CALLS:
            report, error = None, f"tool budget of {MAX_TOOL_CALLS} calls exhausted; Bedrock's report was discarded"
        if not inc.done:  # Bedrock stopped early: finish deterministically, then have it report on the final trace
            first = len(inc.trace)
            while not inc.done:
                inc.step()
            if error is None:
                rest = [_summary(t, inc) for t in inc.trace[first:]]
                report = None  # the first report describes an unfinished incident; never return it as final
                report = str(agent("You stopped before the incident was finished. These steps then ran "
                                   "deterministically:\n" + json.dumps(rest) +
                                   "\nRewrite the full report for the final state.")).strip() or None
                rewritten = report is not None
    except Exception as e:  # Bedrock failed mid-run: the incident still ends safely and the trace is kept
        report, error = None, f"{type(e).__name__}: {e}"
        while not inc.done:
            inc.step()
    usage = agent.event_loop_metrics.accumulated_usage
    # The report is Bedrock's prose and is not checked against the trace: trace and outcome are the record.
    return {**inc.result(explain=False), "mode": "orchestrated", "report": report, "report_after_fallback": rewritten,
            "bedrock_error": error,
            "bedrock_usage": {k: usage.get(k) for k in ("inputTokens", "outputTokens", "totalTokens")},
            "advance_calls": tools[0].calls["advance"]}


if __name__ == "__main__":
    from patterns.capability_aware_router.router import DeciderClient

    from .agent import SCENARIOS
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario", choices=list(SCENARIOS))
    ap.add_argument("--approve", action="store_true",
                    help="scripted pre-approval of every proposal this run makes. Without it a proposed switch stays "
                         "pending; to approve one interactively use python -m simshift.agent or the UI.")
    ap.add_argument("--out", help="write full JSON trace here")
    a = ap.parse_args()
    url = os.environ.get("DECIDER_URL", "http://127.0.0.1:8099")
    res = orchestrate(a.scenario, a.approve, DeciderClient(url))
    res["decider_source"] = f"live {url}"
    if a.out:  # before printing, so a presentation bug can never lose the trace
        write_trace(a.out, res)
    _print(res, res["decider_source"])
    print(f"\nBedrock report, model-written and not checked against the trace; the outcome above is the record "
          f"({res['bedrock_model']}, {res['advance_calls']} advance_recovery call{'' if res['advance_calls'] == 1 else 's'}, "
          f"{res['bedrock_usage']}{', rewritten after a deterministic finish' if res['report_after_fallback'] else ''}):"
          f"\n{res['report'] or res['bedrock_error']}")
