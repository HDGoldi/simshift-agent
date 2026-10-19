"""SIMShift recovery agent.

Each step: observe the twin -> policy excludes inadmissible options -> Strands Decider 2B picks the next
tool -> Strands invokes exactly that tool. Bedrock drafts the profile-change plan and explains the outcome;
it never selects the routine next tool and never authorizes a change.

    python -m simshift.agent BR_PROFILE --approve
"""
from __future__ import annotations

import argparse
import functools
import json
import os
import sys
from dataclasses import asdict
from typing import Callable

from pydantic import BaseModel
from strands import Agent, tool
from strands.hooks import AfterToolCallEvent, BeforeToolCallEvent
from strands.models import BedrockModel

from patterns.capability_aware_router.router import CapabilityAwareRouter, DeciderClient, ReplayDecider

from .policy import FALLBACK, OPTIONS, READ_ONLY, exclusions, guarded_profile_transition, proposal_id
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
MAX_STEPS = 6
BEDROCK_MODEL = os.environ.get("SIMSHIFT_BEDROCK_MODEL", "eu.anthropic.claude-haiku-5-5")
REGION = os.environ.get("AWS_REGION", "eu-central-1")


class ProfilePlan(BaseModel):
    recommend_proceeding: bool
    rationale: str
    risks: list[str]


@functools.cache
def bedrock_model() -> BedrockModel:
    """One Bedrock client per process; creating the boto3 session per incident cost about 0.1 s each."""
    return BedrockModel(model_id=BEDROCK_MODEL, region_name=REGION, max_tokens=2048)


def _bedrock(llm: BedrockModel, prompt: str, schema=None):
    agent = Agent(model=llm, tools=[], callback_handler=None)
    res = agent(prompt, structured_output_model=schema) if schema else agent(prompt)
    return res.structured_output.model_dump() if schema else str(res).strip()


def build_tools(twin: FleetTwin, approver: Callable[[str], bool], llm: BedrockModel | None) -> list:
    """The six routed tools. `approver(proposal_id)` says whether a human approved that exact proposal."""
    plans: dict[str, dict | None] = {}  # one Bedrock review per proposal, even if it is re-submitted after approval

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
        pid = proposal_id(twin, target)
        if llm and pid not in plans:
            try:  # advisory only: a failed review must never keep the proposal from the deterministic gate
                plans[pid] = _bedrock(llm, (
                    "You review a proposed eSIM profile switch for a cohort of cellular IoT devices. This is a simulation. "
                    "Decide whether proceeding is advisable and list concrete risks. You do not authorize anything.\n"
                    f"Observed state: {json.dumps(twin.observe())}\nProfiles: {json.dumps(twin.get_profiles())}\n"
                    f"Proposed target: {target}"), ProfilePlan)
            except Exception as e:  # any Bedrock or structured-output failure is recorded, not raised
                plans[pid] = {"error": f"Bedrock review unavailable: {e!r}"}
        approval = pid if approver(pid) else None
        return {"target": target, "bedrock_plan": plans.get(pid),
                **guarded_profile_transition(twin, target, approval)}

    @tool
    def defer_or_escalate() -> dict:
        """Hold external changes and hand off to a human with the collected evidence."""
        twin.escalate()
        return {"escalated": True, "evidence": twin.observe()["diagnostics"]}

    return [simulate_retry_with_backoff, simulate_operator_reselection, query_firmware_modem_diagnostics,
            query_apn_session_app_diagnostics, prepare_guarded_profile_transition, defer_or_escalate]


def watch_tool_calls(agent: Agent, twin: FleetTwin) -> list[dict]:
    """Independent audit of every tool call: was its option excluded by policy in the state it ran in?
    Recomputed from the policy function, so it still counts violations if the gate itself were broken."""
    option_for, audit = {t: o for o, t in TOOLS.items()}, []

    def before(e):
        option = option_for.get(e.tool_use["name"])
        audit.append({"tool": e.tool_use["name"], "id": e.tool_use["toolUseId"],
                      "excluded": option != FALLBACK and exclusions(twin.observe()).get(option)})

    def after(e):
        next(a for a in reversed(audit) if a["id"] == e.tool_use["toolUseId"])["status"] = e.result["status"]

    agent.add_hook(before, BeforeToolCallEvent)
    agent.add_hook(after, AfterToolCallEvent)
    return audit


def audit_counts(audit: list[dict]) -> dict:
    return {"forbidden_executions": sum(bool(a["excluded"]) and a.get("status") == "success" for a in audit),
            "blocked_calls": sum(bool(a["excluded"]) and a.get("status") != "success" for a in audit)}


def make_router(decider) -> CapabilityAwareRouter:
    return CapabilityAwareRouter(decider=decider, instructions=QUESTION, options=OPTIONS, tools=TOOLS,
                                 policy=exclusions, fallback=FALLBACK, read_only=READ_ONLY)


class Incident:
    """One recovery session. Each step(): observe -> policy -> Decider -> exactly one gated Strands tool.
    The CLI loop, the Bedrock orchestrator and the web UI all drive this same object."""

    def __init__(self, scenario_id: str, approve: bool = False, decider=None, use_bedrock: bool = True):
        self.scenario_id, self.pre_approved, self.use_bedrock = scenario_id, approve, use_bedrock
        self.twin = twin = FleetTwin(scenario_id)
        self.router = make_router(decider or DeciderClient(os.environ.get("DECIDER_URL", "http://127.0.0.1:8099")))
        self.llm = bedrock_model()
        self.approved: set[str] = set()  # proposal ids a human approved during the session
        self.agent = Agent(model=self.llm, tools=build_tools(twin, lambda pid: approve or pid in self.approved,
                                                             self.llm if use_bedrock else None),
                           interventions=[self.router.gate(twin.observe)], callback_handler=None)
        self.audit = watch_tool_calls(self.agent, twin)
        self.initial, self.trace = twin.rates(), []

    def _record(self, decision, result, **extra) -> dict:
        text = result["content"][0]["text"]
        t = {"step": len(self.trace) + 1, "decision": decision and asdict(decision),
             "tool": decision.tool if decision else extra.pop("tool"), "tool_status": result["status"],
             "tool_result": json.loads(text) if result["status"] == "success" else text,
             "rates_after": self.twin.rates(), **extra}
        self.trace.append(t)
        return t

    @property
    def pending_approval(self) -> str | None:
        """Proposal id waiting for a human, if the last step stopped only at the approval check."""
        last = self.trace[-1] if self.trace else None
        gate = last and isinstance(last["tool_result"], dict) and last["tool_result"].get("gate")
        return gate["proposal_id"] if gate and gate["failed"] == ["human_approval"] else None

    @property
    def done(self) -> bool:
        """Restored, handed off, or waiting for a human. A failed, blocked or errored profile change is not an end
        state: the next step hands it off."""
        last = self.trace[-1] if self.trace else None
        return bool(self.twin.service_restored() or self.pending_approval
                    or (last and last["tool"] == TOOLS[FALLBACK]))

    def step(self) -> dict:
        last = self.trace[-1] if self.trace else None
        if last and last["tool"] == TOOLS["evaluate_profile_change"]:  # it did not restore service: hand off
            res = last["tool_result"]
            end = res.get("transition", ["?"])[-1] if isinstance(res, dict) else f"with a tool error: {res}"
            return self._record(None, self.agent.tool.defer_or_escalate(), tool=TOOLS[FALLBACK],
                                note=f"profile change ended {end}; handing off")
        if len(self.trace) >= MAX_STEPS:  # step limit without a terminal action: hand off, never stop silently
            return self._record(None, self.agent.tool.defer_or_escalate(), tool=TOOLS[FALLBACK],
                                note=f"step limit {MAX_STEPS} reached")
        decision, result = self.router.step(self.agent, self.twin.observe())
        return self._record(decision, result)

    def resolve_approval(self, approve: bool) -> dict:
        """A human answers the pending proposal. Approval re-submits that exact proposal through the same gate."""
        pid = self.pending_approval
        if pid is None:
            raise ValueError("no proposal is waiting for approval")
        if not approve:
            return self._record(None, self.agent.tool.defer_or_escalate(), tool=TOOLS[FALLBACK],
                                note=f"operator declined proposal {pid}")
        self.approved.add(pid)
        return self._record(None, self.agent.tool.prepare_guarded_profile_transition(),
                            tool=TOOLS["evaluate_profile_change"], note=f"operator approved proposal {pid}")

    def outcome(self) -> dict:
        t = self.twin
        return {"restored": t.service_restored(), "initial_rates": self.initial, "final_rates": t.rates(),
                "active_profile": t.s["active_profile"], "serving_operator": t.s["serving_operator"],
                "steps": len(self.trace), "simulated_minutes": t.simulated_minutes(),
                "profile_changes": t.profile_changes, **audit_counts(self.audit)}

    def result(self, explain: bool | None = None) -> dict:
        outcome, explanation = self.outcome(), None
        if self.use_bedrock if explain is None else explain:
            try:
                explanation = _bedrock(self.llm, (
                    "Explain in at most 120 words, for a NOC engineer, what this simulated recovery agent did and why. "
                    "Separate what was observed from what is uncertain. Do not invent facts beyond the trace.\n"
                    + json.dumps({"trace": [{k: t[k] for k in ("step", "tool", "tool_result")} |
                                            ({"decider": t["decision"]["raw"], "route": t["decision"]["route"],
                                              "excluded": t["decision"]["excluded"]} if t["decision"] else {"note": t["note"]})
                                            for t in self.trace], "outcome": outcome})))
            except Exception as e:  # the trace matters more than the prose: keep it even if Bedrock fails
                explanation = f"Bedrock explanation unavailable: {e!r}"
        return {"scenario": self.scenario_id, "title": SCENARIOS[self.scenario_id]["title"],
                "approved": self.pre_approved, "bedrock_model": BEDROCK_MODEL if self.use_bedrock else None,
                "trace": self.trace, "outcome": outcome, "explanation": explanation, "events": self.twin.events}


def run(scenario_id: str, approve: bool = False, decider=None, use_bedrock: bool = True) -> dict:
    inc = Incident(scenario_id, approve, decider, use_bedrock)
    while not inc.done:
        inc.step()
    return inc.result()


def _print(r: dict, decider_source: str) -> None:
    bedrock = f"Bedrock {r['bedrock_model']}" if r["bedrock_model"] else "no Bedrock"
    print(f"\n=== {r['scenario']}: {r['title']}  (SIMULATED fleet; Decider: {decider_source}; {bedrock})")
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


def write_trace(path: str, res: dict) -> None:
    """Atomic: an interrupted run never leaves a half-written trace."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path + ".tmp", "w") as f:
        json.dump(res, f, indent=1)
    os.replace(path + ".tmp", path)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario", choices=list(SCENARIOS))
    ap.add_argument("--approve", action="store_true",
                    help="scripted pre-approval of every proposal this run makes (demos, replays, benchmark). "
                         "Without it you are asked to approve the exact proposal when one is pending.")
    ap.add_argument("--no-bedrock", action="store_true")
    ap.add_argument("--out", help="write full JSON trace here")
    ap.add_argument("--replay", metavar="TRACE.json",
                    help="replay the recorded Decider answers from a saved trace instead of calling a Decider server")
    a = ap.parse_args()
    if a.replay:
        with open(a.replay) as f:
            decider, source = ReplayDecider([t["decision"] for t in json.load(f)["trace"]]), f"replay of {a.replay}"
    else:
        url = os.environ.get("DECIDER_URL", "http://127.0.0.1:8099")
        decider, source = DeciderClient(url), f"live {url}"
    inc = Incident(a.scenario, approve=a.approve, decider=decider, use_bedrock=not a.no_bedrock)
    while True:
        while not inc.done:
            inc.step()
        if not (inc.pending_approval and sys.stdin.isatty()):
            break  # no proposal waiting, or nobody at a terminal to answer it: it stays pending
        gate = inc.trace[-1]["tool_result"]["gate"]
        try:
            answer = input(f"\nApprove proposal {inc.pending_approval}: enable {gate['target']} on "
                           f"{inc.twin.s['devices']} devices? Every other check passed. [y/N] ")
        except EOFError:
            break  # no answer: the proposal stays pending
        inc.resolve_approval(answer.strip().lower() == "y")
    res = inc.result()
    res["decider_source"] = source
    _print(res, source)
    if a.out:
        write_trace(a.out, res)
