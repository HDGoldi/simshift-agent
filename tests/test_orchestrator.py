"""The Strands event loop runs for real; only the Bedrock model is replaced by a scripted one (no AWS)."""
import json

import pytest

from strands.models import Model

from simshift.orchestrator import orchestrate, orchestrator_tools
from simshift.agent import Incident
from simshift.simulator import SCENARIOS
from tests.test_agent import ScriptedDecider


class ScriptedModel(Model):
    """Plays back turns, each ("tool", name, input) or ("text", str), and records what the LLM was shown."""

    def __init__(self, turns):
        self.turns, self.i, self.specs, self.seen = list(turns), 0, [], []

    def update_config(self, **kw): ...
    def get_config(self): return {}
    def structured_output(self, *a, **kw): raise NotImplementedError

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kw):
        self.specs.append(tool_specs or [])
        self.seen.append(json.dumps(messages))
        kind, *rest = self.turns[self.i] if self.i < len(self.turns) else ("text", "REPORT")
        self.i += 1
        yield {"messageStart": {"role": "assistant"}}
        if kind == "tool":
            name, args = rest
            yield {"contentBlockStart": {"start": {"toolUse": {"toolUseId": f"t{self.i}", "name": name}}}}
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(args)}}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        else:
            yield {"contentBlockDelta": {"delta": {"text": rest[0]}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}
        yield {"metadata": {"usage": {"inputTokens": 10, "outputTokens": 5, "totalTokens": 15}, "metrics": {"latencyMs": 1}}}


ADVANCE = ("tool", "advance_recovery", {})


@pytest.fixture(autouse=True)
def no_aws(monkeypatch):  # the profile-plan review would otherwise call real Bedrock
    import simshift.agent as ag
    monkeypatch.setattr(ag, "_bedrock", lambda llm, prompt, schema=None:
                        {"recommend_proceeding": True, "rationale": "stub", "risks": []} if schema else "stub")


def test_bedrock_sees_two_tools_without_arguments():
    specs = [t.tool_spec for t in orchestrator_tools(Incident("BR_PROFILE", decider=ScriptedDecider([]), use_bedrock=False))]
    assert sorted(s["name"] for s in specs) == ["advance_recovery", "get_incident_state"]
    assert all(not s["inputSchema"]["json"].get("properties") for s in specs)


def test_decider_choice_is_what_runs_even_if_bedrock_asks_for_another():
    model = ScriptedModel([("tool", "get_incident_state", {}),
                           ("tool", "advance_recovery", {"tool": "prepare_guarded_profile_transition"}),  # ignored
                           ADVANCE, ("text", "REPORT")])
    r = orchestrate("BR_PROFILE", approve=True, model=model,
                    decider=ScriptedDecider(["investigate_device", "evaluate_profile_change"]))
    assert [t["tool"] for t in r["trace"]] == ["query_firmware_modem_diagnostics", "prepare_guarded_profile_transition"]
    assert r["outcome"]["restored"] and r["report"] == "REPORT" and r["advance_calls"] == 2
    assert all(sorted(s["name"] for s in specs) == ["advance_recovery", "get_incident_state"] for specs in model.specs)


def test_bedrock_cannot_approve_or_bypass_the_gate():
    r = orchestrate("BR_PROFILE", approve=False, model=ScriptedModel([ADVANCE, ADVANCE, ADVANCE]),
                    decider=ScriptedDecider(["investigate_device", "evaluate_profile_change"]))
    assert not r["outcome"]["restored"] and r["trace"][-1]["tool_result"]["gate"]["failed"] == ["human_approval"]
    assert not any(e["kind"] == "eim_enable_profile" for e in r["events"])


def test_bedrock_stopping_early_still_finishes_safely():
    r = orchestrate("OFFLINE", model=ScriptedModel([("text", "done already")]),
                    decider=ScriptedDecider(["investigate_data_path"]))
    assert r["advance_calls"] == 0 and r["trace"][-1]["decision"]["selected"] == "escalate_or_wait"


def test_no_hidden_truth_reaches_bedrock():
    for sid, sc in SCENARIOS.items():
        model = ScriptedModel([("tool", "get_incident_state", {})] + [ADVANCE] * 8)
        orchestrate(sid, approve=True, model=model, decider=ScriptedDecider(["investigate_data_path"]))
        sent = "".join(model.seen)
        for secret in (sc["hidden"]["cause"], sid, "best_actions", '"networks"', "ingestion_healthy",
                       "device_powered", '"hidden"', "firmware_fault", "transient_congestion"):
            assert secret not in sent, (sid, secret)


def test_report_is_rewritten_after_a_deterministic_finish():
    model = ScriptedModel([("text", "STALE"), ("text", "FINAL REPORT")])
    r = orchestrate("OFFLINE", model=model, decider=ScriptedDecider(["investigate_data_path"]))
    assert r["advance_calls"] == 0 and r["report_after_fallback"] and r["report"] == "FINAL REPORT"
    assert "ran deterministically" in model.seen[-1]


def test_bedrock_failure_still_finishes_the_incident():
    class Broken(ScriptedModel):
        async def stream(self, *a, **k):
            raise RuntimeError("throttled")
            yield  # never reached; makes this an async generator like the real stream()
    r = orchestrate("OFFLINE", model=Broken([]), decider=ScriptedDecider(["investigate_data_path"]))
    assert r["report"] is None and "throttled" in r["bedrock_error"]
    assert r["trace"][-1]["tool"] == "defer_or_escalate"


def test_tool_budget_stops_a_runaway_model():
    model = ScriptedModel([("tool", "get_incident_state", {})] * 100)
    r = orchestrate("OFFLINE", model=model, decider=ScriptedDecider(["investigate_data_path"]))
    assert model.i <= 20 and r["trace"][-1]["tool"] == "defer_or_escalate"


def test_advance_calls_counts_every_call():
    model = ScriptedModel([ADVANCE, ADVANCE, ("text", "REPORT")])
    r = orchestrate("OFFLINE", model=model, decider=ScriptedDecider(["investigate_data_path"]))
    assert r["advance_calls"] == len(r["trace"]) == 2


def test_failed_rewrite_never_returns_the_stale_report():
    class StaleThenBroken(ScriptedModel):
        async def stream(self, messages, tool_specs=None, system_prompt=None, **kw):
            if self.i:
                raise RuntimeError("throttled")
            async for e in super().stream(messages, tool_specs, system_prompt, **kw):
                yield e
    r = orchestrate("OFFLINE", model=StaleThenBroken([("text", "STALE")]), decider=ScriptedDecider(["investigate_data_path"]))
    assert r["report"] is None and "throttled" in r["bedrock_error"] and r["trace"][-1]["tool"] == "defer_or_escalate"


def test_budget_exhaustion_is_reported():
    model = ScriptedModel([("tool", "get_incident_state", {})] * 100)
    r = orchestrate("OFFLINE", model=model, decider=ScriptedDecider(["investigate_data_path"]))
    assert r["report"] is None and "budget" in r["bedrock_error"]
