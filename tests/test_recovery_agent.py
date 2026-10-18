"""Strands wiring tests with a scripted stand-in for Bedrock (no AWS call, no model server).

The scripted model emits Bedrock ConverseStream-shaped events, so the real Strands event loop
runs, executes our tools, and feeds results back -- only the LLM itself is replaced.
"""

from __future__ import annotations

import json
import os
from typing import Any

import pytest
from strands.models import Model

from agent.recovery_agent import RecoverySession, build_agent, run
from patterns.capability_aware_router import Decision, HttpDeciderClient
from simulator import scenarios


class FakeDecider:
    def __init__(self, choice: str | None = None) -> None:
        self.choice, self.calls = choice, 0

    def choose(self, state, question, criteria):
        self.calls += 1
        c = self.choice or next(iter(criteria))
        return Decision(choice=c, probabilities={c: 0.7}, confidence=0.4, model="fake-decider")


class ScriptedModel(Model):
    """Plays back turns: each turn is ('tool', name, input) or ('text', str)."""

    def __init__(self, turns: list[tuple]) -> None:
        self.turns, self.i = turns, 0
        self.tool_specs_seen: list[list[str]] = []
        self.tool_results_seen: list[Any] = []

    def update_config(self, **kw: Any) -> None: ...
    def get_config(self) -> dict: return {}
    def structured_output(self, *a: Any, **kw: Any):  # pragma: no cover
        raise NotImplementedError

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kw: Any):
        self.tool_specs_seen.append([t["name"] for t in (tool_specs or [])])
        for m in messages:
            for block in m.get("content", []):
                if "toolResult" in block:
                    self.tool_results_seen.append(block["toolResult"])
        turn = self.turns[self.i]
        self.i += 1
        yield {"messageStart": {"role": "assistant"}}
        if turn[0] == "tool":
            _, name, args = turn
            yield {"contentBlockStart": {"start": {"toolUse": {"toolUseId": f"t{self.i}", "name": name}}}}
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(args)}}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        else:
            yield {"contentBlockDelta": {"delta": {"text": turn[1]}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}
        yield {"metadata": {"usage": {"inputTokens": 10, "outputTokens": 5, "totalTokens": 15},
                            "metrics": {"latencyMs": 1}}}


HAPPY = [("tool", "get_incident_state", {}), ("tool", "advance_recovery", {}), ("text", "REPORT")]


def test_llm_only_sees_two_tools_and_cannot_name_an_action():
    s = RecoverySession("profile_recovery", FakeDecider())
    specs = {t.tool_spec["name"]: t.tool_spec for t in s.tools()}
    assert set(specs) == {"get_incident_state", "advance_recovery"}
    for spec in specs.values():
        assert spec["inputSchema"]["json"].get("properties", {}) == {}


def test_strands_loop_runs_router_and_decider_choice_is_what_ran():
    model = ScriptedModel(HAPPY)
    out = run("profile_recovery", FakeDecider("evaluate_profile_change"), model=model)
    assert out["report"].strip() == "REPORT"
    assert len(out["steps"]) == 1
    step = out["steps"][0]
    assert step["choice"] == step["executed"] == "evaluate_profile_change"
    assert step["tool"] == "prepare_guarded_profile_transition"
    # recovery tools were never offered to the LLM
    assert all(set(names) == {"get_incident_state", "advance_recovery"} for names in model.tool_specs_seen)


def test_llm_args_cannot_steer_the_choice():
    """Even if the LLM stuffs an argument into the call, the router -- not the LLM -- decides."""
    model = ScriptedModel([("tool", "advance_recovery", {"option": "evaluate_profile_change"}), ("text", "R")])
    out = run("unreachable_device", FakeDecider("escalate_or_wait"), model=model)
    assert all(s["executed"] != "evaluate_profile_change" for s in out["steps"])


def test_step_budget_enforced():
    d = FakeDecider()
    model = ScriptedModel([("tool", "advance_recovery", {}), ("tool", "advance_recovery", {}), ("text", "R")])
    out = run("profile_recovery", d, model=model, max_steps=1)
    assert d.calls == 1 and len(out["steps"]) == 1
    assert "step budget spent" in json.dumps(model.tool_results_seen[-1])


@pytest.mark.parametrize("name", scenarios.names())
def test_no_truth_reaches_llm(name):
    model = ScriptedModel(HAPPY)
    run(name, FakeDecider(), model=model)
    seen = json.dumps(model.tool_results_seen)
    assert scenarios.load(name)["evaluator_only"]["true_cause"] not in seen


@pytest.mark.live
@pytest.mark.skipif(os.environ.get("SIMSHIFT_LIVE_BEDROCK") != "1", reason="set SIMSHIFT_LIVE_BEDROCK=1")
def test_live_bedrock_and_decider():
    out = run("profile_recovery", HttpDeciderClient())
    assert out["steps"] and out["steps"][0]["model"].startswith("strands-decider-2B")
    assert out["report"] and out["bedrock_usage"]


def test_build_agent_accepts_injected_model():
    agent = build_agent(RecoverySession("profile_recovery", FakeDecider()), model=ScriptedModel(HAPPY))
    assert set(agent.tool_names) == {"get_incident_state", "advance_recovery"}
