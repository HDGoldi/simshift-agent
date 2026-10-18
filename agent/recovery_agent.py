"""SIMShift Strands agent: Bedrock orchestrates and explains; Decider 2B picks the recovery tool.

Role split (enforced by the tool surface, not by the prompt):
  * Bedrock (via Strands) sees two tools: `get_incident_state` and `advance_recovery`.
  * `advance_recovery` takes NO arguments. Bedrock cannot name a recovery action; it can only
    ask for the next step. Inside, the policy filters options, Strands Decider 2B chooses, the
    chosen tool acts on the digital twin, and a profile change additionally needs the human
    approval gate (`approve`), which Bedrock cannot reach.
  * Hidden scenario truth never reaches either tool.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from strands import Agent, tool

from agent.incident import Approver, Incident, deny_all
from patterns.capability_aware_router import DeciderClient
from simulator import scenarios

SYSTEM_PROMPT = """You are SIMShift, a recovery agent for a SIMULATED cellular IoT fleet.

Procedure:
1. Call get_incident_state once.
2. Call advance_recovery. Each call runs ONE recovery step; a separate decision model chooses
   which tool runs, and you cannot choose or override it. Repeat until a result has
   "terminal": true, or returns an error saying the budget is spent, or "executed" is null.
3. Write a short report for a fleet operations engineer with these headings:
   - What happened: the symptoms, in two sentences.
   - Decisions: for each step, the option chosen, its confidence, and options removed by policy.
   - Outcome: registration and application rates after the last step; whether service is restored;
     any profile change and whether it was approved.
   - Next: what a human should check or do now.

Rules: quote numbers only from tool results; never invent measurements. Everything is simulated;
say so once. Keep the report under 250 words."""


class RecoverySession:
    def __init__(self, scenario: str, decider: DeciderClient, approve: Approver = deny_all,
                 max_steps: int = 5, seed: int = 7) -> None:
        self.scenario = scenario
        self.incident = Incident(scenario, decider, approve=approve, seed=seed, max_steps=max_steps)

    @property
    def steps(self) -> list[dict[str, Any]]:
        return self.incident.steps

    def tools(self) -> list[Any]:
        inc = self.incident

        @tool
        def get_incident_state() -> str:
            """Return the current observable state of the incident cohort as plain text."""
            return scenarios.describe(inc.twin.observe())

        @tool
        def advance_recovery() -> str:
            """Run ONE recovery step. A policy filters unsafe options, a decision model picks the
            next tool, and it runs on the simulated fleet. Returns the decision, the tool result
            and the state afterwards as JSON."""
            if inc.done:
                return json.dumps({"error": "incident finished or step budget spent; write the report now",
                                   "terminal": True})
            return json.dumps(inc.step(), default=str)

        return [get_incident_state, advance_recovery]


def build_agent(session: RecoverySession, model: Any | None = None) -> Agent:
    if model is None:
        from agent.bedrock import make_model

        model = make_model()
    return Agent(model=model, tools=session.tools(), system_prompt=SYSTEM_PROMPT, callback_handler=None)


def run(scenario: str, decider: DeciderClient, model: Any | None = None,
        approve: Approver = deny_all, max_steps: int = 5) -> Mapping[str, Any]:
    session = RecoverySession(scenario, decider, approve=approve, max_steps=max_steps)
    agent = build_agent(session, model)
    result = agent(f"New incident cohort: {scenario}. Follow your procedure.")
    usage = getattr(getattr(result, "metrics", None), "accumulated_usage", None)
    return {
        "scenario": scenario,
        "steps": session.steps,
        "outcome": session.incident.twin.outcome(),
        "report": str(result),
        "bedrock_usage": dict(usage) if usage else None,
    }
