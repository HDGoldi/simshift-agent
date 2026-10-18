"""CapabilityAwareRouter: a reusable Strands Decider 2B tool-selection pattern.

    state -> deterministic policy removes inadmissible options -> Decider `choice` question over the rest
          -> confidence-aware route -> the chosen Strands tool is invoked (agent.tool.<name>)

The policy also runs as a Strands InterventionHandler, so the same rules gate every call to a routed
tool, whether Decider, an LLM, or a person triggered it. The decision model never authorizes anything.
"""
from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

from strands import InterventionHandler
from strands.interventions import Deny, Proceed

# Pinned: strands-labs/strands-decider @ 930e6d5d, checkpoint below, served with `strands-decider serve`.
DECIDER_MODEL = "StrandsAgents/strands-decider-2B-qwen3.5-v1-2610"

Policy = Callable[[Any], dict[str, str]]  # state -> {excluded option: reason}


class DeciderClient:
    """Minimal client for the Decider HTTP API (POST /v1/systemone). One request at a time."""

    def __init__(self, url: str = "http://127.0.0.1:8099", timeout: float = 60.0):
        self.url, self.timeout = url.rstrip("/"), timeout

    def choose(self, state: Any, instructions: str, options: dict[str, str], name: str = "next_tool") -> dict:
        body = {"state": state, "questions": {name: {"type": "choice", "instructions": instructions, "criteria": options}}}
        req = urllib.request.Request(f"{self.url}/v1/systemone", json.dumps(body).encode(),
                                     {"content-type": "application/json"})
        t0 = time.perf_counter()
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            resp = json.load(r)
        ans = resp["answers"][name]
        return {"choice": ans["choice"], "probabilities": ans["probabilities"], "confidence": ans["confidence"],
                "model": resp.get("model"), "latency_ms": resp.get("latency_ms"),
                "client_latency_ms": round((time.perf_counter() - t0) * 1000, 1)}


class ReplayDecider:
    """Replays recorded Decider answers in order (from Decision.raw in a saved trace). Refuses if the live
    question differs from the recorded one, so a stale answer is never applied to a different state."""

    def __init__(self, decisions: list[dict]):
        self.pending = [d for d in decisions if d and d.get("raw")]  # recorded errors are replayed too

    def choose(self, state: Any, instructions: str, options: dict[str, str], name: str = "next_tool") -> dict:
        if not self.pending:
            raise ValueError("replay exhausted: no recorded answer left")
        d = self.pending.pop(0)
        if (json.loads(json.dumps(state)), instructions, options) != (d["state"], d["question"], d["eligible"]):
            raise ValueError("replay mismatch: live question differs from the recorded one")
        if "error" in d["raw"]:
            raise OSError(f"replayed recorded Decider failure: {d['raw']['error']}")
        return {**d["raw"], "replayed": True}


@dataclass
class Decision:
    question: str
    state: Any
    eligible: dict[str, str]
    excluded: dict[str, str]
    raw: dict | None  # exact Decider answer; None if no model call was needed
    selected: str  # option actually routed
    route: str  # "act" | "gather_evidence" | "fallback"
    reason: str
    tool: str = ""


@dataclass
class CapabilityAwareRouter:
    decider: DeciderClient
    instructions: str  # the typed question
    options: dict[str, str]  # option -> description (shown to Decider)
    tools: dict[str, str]  # option -> registered Strands tool name
    policy: Policy
    fallback: str  # always-admissible option for "not sure": hand off, hold, escalate
    read_only: frozenset[str] = field(default_factory=frozenset)  # safe to run when unsure
    act_threshold: float = 0.5  # tune on held-out cases; derived confidence, not calibrated probability

    def decide(self, state: Any, decider_state: Any = None) -> Decision:
        excluded = {k: v for k, v in self.policy(state).items() if k in self.options and k != self.fallback}
        eligible = {k: v for k, v in self.options.items() if k not in excluded}
        if len(eligible) == 1:  # nothing to decide
            return Decision(self.instructions, decider_state or state, eligible, excluded, None, self.fallback,
                            "fallback", "only the fallback is admissible", self.tools[self.fallback])
        try:
            raw = self.decider.choose(decider_state if decider_state is not None else state, self.instructions, eligible)
            if not (isinstance(raw.get("choice"), str) and isinstance(raw.get("probabilities"), dict)
                    and isinstance(raw.get("confidence"), (int, float))):
                raise ValueError(f"malformed Decider answer: {raw!r}")
        except (OSError, ValueError, KeyError, TypeError) as e:  # fail closed: Decider down, timeout, bad response
            return Decision(self.instructions, decider_state or state, eligible, excluded, {"error": repr(e)},
                            self.fallback, "fallback", "decider unavailable", self.tools[self.fallback])
        if raw["choice"] not in eligible:  # fail closed: never route outside the admissible set
            return Decision(self.instructions, decider_state if decider_state is not None else state, eligible,
                            excluded, raw, self.fallback, "fallback",
                            f"Decider returned non-admissible option {raw['choice']!r}", self.tools[self.fallback])
        if raw["confidence"] >= self.act_threshold:
            sel, route, why = raw["choice"], "act", f"confidence {raw['confidence']:.2f} >= {self.act_threshold}"
        else:
            safe = [o for o in sorted(eligible, key=lambda o: -raw["probabilities"].get(o, 0)) if o in self.read_only]
            if safe:
                sel, route = safe[0], "gather_evidence"
                why = f"confidence {raw['confidence']:.2f} < {self.act_threshold}: most probable read-only option"
            else:
                sel, route = self.fallback, "fallback"
                why = f"confidence {raw['confidence']:.2f} < {self.act_threshold} and no read-only option left"
        return Decision(self.instructions, decider_state if decider_state is not None else state,
                        eligible, excluded, raw, sel, route, why, self.tools[sel])

    def step(self, agent, state: Any, decider_state: Any = None, **tool_args) -> tuple[Decision, dict]:
        """Decide, then invoke the selected tool through Strands (recorded in agent.messages, gated)."""
        d = self.decide(state, decider_state)
        return d, getattr(agent.tool, d.tool)(**tool_args)

    def gate(self, state_fn: Callable[[], Any]) -> InterventionHandler:
        """InterventionHandler that re-checks the policy right before any routed tool executes."""
        return _PolicyGate(self, state_fn)


class _PolicyGate(InterventionHandler):
    name = "capability-aware-router-gate"

    def __init__(self, router: CapabilityAwareRouter, state_fn: Callable[[], Any]):
        self.router, self.state_fn = router, state_fn
        self.option_for = {t: o for o, t in router.tools.items()}

    @property
    def on_error(self):
        return "deny"  # fail closed

    def before_tool_call(self, event, **kwargs):
        option = self.option_for.get(event.tool_use["name"])
        if option is None:
            return Proceed()
        reason = self.router.policy(self.state_fn()).get(option)
        return Deny(reason=f"{option} inadmissible: {reason}") if reason and option != self.router.fallback else Proceed()
