"""SIMShift recovery agent.

Each step: observe the twin -> policy excludes inadmissible options -> Strands Decider 2B picks the next
tool -> Strands invokes exactly that tool. Bedrock drafts the profile-change plan and explains the outcome;
it never selects the routine next tool and never authorizes a change.

    python -m simshift.agent BR_PROFILE --approve
"""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict

from pydantic import BaseModel
from strands import Agent, tool
from strands.models import BedrockModel

from patterns.capability_aware_router.router import CapabilityAwareRouter, DeciderClient

from .policy import FALLBACK, OPTIONS, READ_ONLY, exclusions, guarded_profile_transition
from .simulator import SCENARIOS, FleetTwin

QUESTION = ("Given the cellular connectivity symptoms, diagnostic evidence so far, and only these admissible tools, "
            "which next tool is most useful for safely advancing service restoration? "
            "Do not assume an unverified recovery path works.")
TOOLS = {
    "retry_connection": "simulate_retry_with_backoff",
    "try_allowed_operator": "simulate_operator_reselection",
    "investigate_device": "query_firmware_modem_diagnostics",
    "investigate_data_path": "query_apn_session_app_diagnostics",
    "evaluate_profile_change": "prepare_guarded_profile_transition",
    "escalate_or_wait": "defer_or_escalate",
}
TERMINAL = {"evaluate_profile_change", "escalate_or_wait"}
MAX_STEPS = 6
BEDROCK_MODEL = os.environ.get("SIMSHIFT_BEDROCK_MODEL", "eu.anthropic.claude-haiku-5-5")
REGION = os.environ.get("AWS_REGION", "eu-central-1")


class ProfilePlan(BaseModel):
    recommend_proceeding: bool
    rationale: str
    risks: list[str]


def _bedrock(llm: BedrockModel, prompt: str, schema=None):
    agent = Agent(model=llm, tools=[], callback_handler=None)
    res = agent(prompt, structured_output_model=schema) if schema else agent(prompt)
    return res.structured_output.model_dump() if schema else str(res).strip()


def build_tools(twin: FleetTwin, approve: bool, llm: BedrockModel | None) -> list:
    @tool
    def simulate_retry_with_backoff() -> dict:
        """Bounded backoff and re-attach on the current profile and operator (simulated)."""
        return twin.retry_with_backoff()

    @tool
    def simulate_operator_reselection() -> dict:
        """Reselect another operator allowed by the active profile; no eSIM profile change (simulated)."""
        return twin.operator_reselection()

    @tool
    def query_firmware_modem_diagnostics() -> dict:
        """Read-only modem/firmware diagnostics for the cohort."""
        return twin.firmware_modem_diagnostics()

    @tool
    def query_apn_session_app_diagnostics() -> dict:
        """Read-only network-side session, APN and application-ingestion diagnostics."""
        return twin.data_path_diagnostics()

    @tool
    def prepare_guarded_profile_transition() -> dict:
        """Bedrock plan -> deterministic gate + human approval -> virtual eIM enable -> verify -> rollback on failure."""
        target = next(p for p in twin.s["profiles"] if p != twin.s["active_profile"])
        plan = None
        if llm:
            plan = _bedrock(llm, (
                "You review a proposed eSIM profile switch for a cohort of cellular IoT devices. This is a simulation. "
                "Decide whether proceeding is advisable and list concrete risks. You do not authorize anything.\n"
                f"Observed state: {json.dumps(twin.observe())}\nProfiles: {json.dumps(twin.get_profiles())}\n"
                f"Proposed target: {target}"), ProfilePlan)
        return {"target": target, "bedrock_plan": plan, **guarded_profile_transition(twin, target, approved=approve)}

    @tool
    def defer_or_escalate() -> dict:
        """Hold external changes and hand off to a human with the collected evidence."""
        return {"escalated": True, "evidence": twin.observe()["diagnostics"]}

    return [simulate_retry_with_backoff, simulate_operator_reselection, query_firmware_modem_diagnostics,
            query_apn_session_app_diagnostics, prepare_guarded_profile_transition, defer_or_escalate]


def make_router(decider) -> CapabilityAwareRouter:
    return CapabilityAwareRouter(decider=decider, instructions=QUESTION, options=OPTIONS, tools=TOOLS,
                                 policy=exclusions, fallback=FALLBACK, read_only=READ_ONLY)


def run(scenario_id: str, approve: bool = False, decider=None, use_bedrock: bool = True) -> dict:
    twin = FleetTwin(scenario_id)
    router = make_router(decider or DeciderClient(os.environ.get("DECIDER_URL", "http://127.0.0.1:8099")))
    llm = BedrockModel(model_id=BEDROCK_MODEL, region_name=REGION, max_tokens=2048)
    agent = Agent(model=llm, tools=build_tools(twin, approve, llm if use_bedrock else None),
                  interventions=[router.gate(twin.observe)], callback_handler=None)
    initial, trace = twin.rates(), []
    for step in range(1, MAX_STEPS + 1):
        decision, result = router.step(agent, twin.observe())
        text = result["content"][0]["text"]
        trace.append({"step": step, "decision": asdict(decision), "tool": decision.tool, "tool_status": result["status"],
                      "tool_result": json.loads(text) if result["status"] == "success" else text,
                      "rates_after": twin.rates()})
        if twin.service_restored() or decision.selected in TERMINAL:
            break
    else:  # step limit reached without a terminal action: hand off, never stop silently
        result = agent.tool.defer_or_escalate()
        trace.append({"step": MAX_STEPS + 1, "decision": None, "tool": TOOLS[FALLBACK], "tool_status": result["status"],
                      "tool_result": json.loads(result["content"][0]["text"]), "rates_after": twin.rates(),
                      "note": f"step limit {MAX_STEPS} reached"})
    outcome = {"restored": twin.service_restored(), "initial_rates": initial, "final_rates": twin.rates(),
               "active_profile": twin.s["active_profile"], "serving_operator": twin.s["serving_operator"],
               "steps": len(trace)}
    explanation = None
    if use_bedrock:
        explanation = _bedrock(llm, (
            "Explain in at most 120 words, for a NOC engineer, what this simulated recovery agent did and why. "
            "Separate what was observed from what is uncertain. Do not invent facts beyond the trace.\n"
            + json.dumps({"trace": [{k: t[k] for k in ("step", "tool", "tool_result")} |
                                    ({"decider": t["decision"]["raw"], "route": t["decision"]["route"],
                                      "excluded": t["decision"]["excluded"]} if t["decision"] else {"note": t["note"]})
                                    for t in trace], "outcome": outcome})))
    return {"scenario": scenario_id, "title": SCENARIOS[scenario_id]["title"], "approved": approve,
            "bedrock_model": BEDROCK_MODEL if use_bedrock else None, "trace": trace, "outcome": outcome,
            "explanation": explanation, "events": twin.events}


def _print(r: dict) -> None:
    print(f"\n=== {r['scenario']}: {r['title']}  (SIMULATED fleet; real Decider + Bedrock calls)")
    o = r["outcome"]
    print(f"initial: {o['initial_rates']}")
    for t in r["trace"]:
        d = t["decision"]
        if d is None:
            print(f"\n[{t['step']}] {t['note']} -> tool {t['tool']}")
            continue
        raw = d["raw"] or {}
        probs = ", ".join(f"{k}={v:.2f}" for k, v in sorted(raw.get("probabilities", {}).items(), key=lambda kv: -kv[1]))
        print(f"\n[{t['step']}] excluded: {d['excluded'] or '-'}")
        print(f"    Decider: choice={raw.get('choice')} conf={raw.get('confidence', 0):.2f} ({probs}) {raw.get('latency_ms')}ms")
        print(f"    route={d['route']} ({d['reason']}) -> tool {t['tool']} [{t['tool_status']}]")
        print(f"    result: {json.dumps(t['tool_result'])[:400]}")
        plan = t["tool_result"].get("bedrock_plan") if isinstance(t["tool_result"], dict) else None
        if plan:
            print(f"    Bedrock plan: recommend_proceeding={plan['recommend_proceeding']}: {plan['rationale']}")
    print(f"\noutcome: restored={o['restored']} profile={o['active_profile']} operator={o['serving_operator']} final={o['final_rates']}")
    if r["explanation"]:
        print(f"\nBedrock ({r['bedrock_model']}): {r['explanation']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario", choices=list(SCENARIOS))
    ap.add_argument("--approve", action="store_true", help="operator pre-approves a profile switch if one is proposed")
    ap.add_argument("--no-bedrock", action="store_true")
    ap.add_argument("--out", help="write full JSON trace here")
    a = ap.parse_args()
    res = run(a.scenario, approve=a.approve, use_bedrock=not a.no_bedrock)
    _print(res)
    if a.out:
        os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
        with open(a.out, "w") as f:
            json.dump(res, f, indent=1)
