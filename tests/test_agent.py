import json
import os
import urllib.request

import pytest

from patterns.capability_aware_router.router import DECIDER_MODEL, DeciderClient
from simshift.agent import TOOLS, run
from simshift.simulator import SCENARIOS


class ScriptedDecider:
    """Returns a scripted choice (if admissible) and records every state it was shown."""

    def __init__(self, choices):
        self.choices, self.calls = list(choices), []

    def choose(self, state, instructions, options, name="next_tool"):
        self.calls.append(json.dumps(state))
        c = self.choices.pop(0) if self.choices else "escalate_or_wait"
        assert c in options, f"test scripted a non-admissible choice {c}"
        return {"choice": c, "probabilities": {o: float(o == c) for o in options}, "confidence": 1.0}


def test_decider_controls_tool():
    a = run("BR_PROFILE", decider=ScriptedDecider(["investigate_device"]), use_bedrock=False)
    b = run("BR_PROFILE", decider=ScriptedDecider(["investigate_data_path"]), use_bedrock=False)
    assert a["trace"][0]["tool"] == TOOLS["investigate_device"] == "query_firmware_modem_diagnostics"
    assert b["trace"][0]["tool"] == TOOLS["investigate_data_path"]
    assert a["events"][0]["kind"] == "diagnostics_device" and b["events"][0]["kind"] == "diagnostics_data_path"


def test_brazil_end_to_end_with_approval():
    r = run("BR_PROFILE", approve=True, decider=ScriptedDecider(["investigate_device", "evaluate_profile_change"]),
            use_bedrock=False)
    assert r["outcome"]["restored"] and r["outcome"]["active_profile"] == "profile_B"
    without = run("BR_PROFILE", approve=False, decider=ScriptedDecider(["investigate_device", "evaluate_profile_change"]),
                  use_bedrock=False)
    assert not without["outcome"]["restored"] and without["trace"][-1]["tool_result"]["gate"]["failed"] == ["human_approval"]


def test_unreachable_never_executes_profile_change():
    r = run("OFFLINE", approve=True, decider=ScriptedDecider(["investigate_data_path"]), use_bedrock=False)
    assert not any(e["kind"].startswith("eim_") for e in r["events"])
    assert r["trace"][-1]["decision"]["selected"] == "escalate_or_wait"


def test_no_truth_leakage():
    for sid, sc in SCENARIOS.items():
        dec = ScriptedDecider(["investigate_data_path"])
        r = run(sid, approve=True, decider=dec, use_bedrock=False)
        sent = "".join(dec.calls) + json.dumps([t["decision"]["state"] for t in r["trace"]])
        for secret in (sc["hidden"]["cause"], sid, "best_actions", '"networks"', "ingestion_healthy"):
            assert secret not in sent, (sid, secret)


def _decider_up(url):
    try:
        return json.load(urllib.request.urlopen(f"{url}/health", timeout=2))["status"] == "ok"
    except OSError:
        return False


URL = os.environ.get("DECIDER_URL", "http://127.0.0.1:8099")


@pytest.mark.skipif(not _decider_up(URL), reason="Decider server not running")
def test_decider_is_real():
    r = run("BR_PROFILE", approve=True, decider=DeciderClient(URL), use_bedrock=False)
    raw = r["trace"][0]["decision"]["raw"]
    assert raw["model"] == DECIDER_MODEL.split("/")[-1]
    assert abs(sum(raw["probabilities"].values()) - 1) < 1e-3 and raw["choice"] in raw["probabilities"]
    assert all(t["tool"] == TOOLS[t["decision"]["selected"]] for t in r["trace"])


def test_step_limit_escalates(monkeypatch):
    import simshift.agent as ag
    monkeypatch.setattr(ag, "MAX_STEPS", 1)
    r = ag.run("BR_PROFILE", decider=ScriptedDecider(["investigate_device"]), use_bedrock=False)
    assert r["trace"][-1]["tool"] == "defer_or_escalate" and "step limit" in r["trace"][-1]["note"]


def test_no_truth_leakage_in_bedrock_prompts(monkeypatch):
    import simshift.agent as ag
    prompts = []

    def fake_bedrock(llm, prompt, schema=None):
        prompts.append(prompt)
        return {"recommend_proceeding": True, "rationale": "", "risks": []} if schema else "ok"

    monkeypatch.setattr(ag, "_bedrock", fake_bedrock)
    for sid, sc in SCENARIOS.items():
        prompts.clear()
        dec = ScriptedDecider(["investigate_device", "evaluate_profile_change"] if sid == "BR_PROFILE"
                              else ["investigate_data_path"])
        r = ag.run(sid, approve=True, decider=dec)
        sent = "".join(prompts) + "".join(dec.calls)
        assert prompts, sid
        if sid == "BR_PROFILE":
            assert r["outcome"]["restored"] and len(prompts) == 2  # plan + explanation both checked
        for secret in (sc["hidden"]["cause"], sid, "best_actions", '"networks"', "ingestion_healthy",
                       "device_powered", '"hidden"'):
            assert secret not in sent, (sid, secret)


class OffMenuDecider:
    """Always answers evaluate_profile_change, whether or not it was offered."""

    def choose(self, state, instructions, options, name="next_tool"):
        return {"choice": "evaluate_profile_change", "probabilities": {o: 0.0 for o in options}, "confidence": 1.0}


def test_off_menu_choice_never_reaches_the_eim():
    r = run("OFFLINE", approve=True, decider=OffMenuDecider(), use_bedrock=False)
    d = r["trace"][0]["decision"]
    assert "evaluate_profile_change" in d["excluded"] and (d["selected"], d["route"]) == ("escalate_or_wait", "fallback")
    assert not any(e["kind"].startswith("eim_") for e in r["events"])


SAMPLE_RUNS = os.path.join(os.path.dirname(__file__), "..", "docs", "sample-runs")


@pytest.mark.parametrize("name", sorted(os.listdir(SAMPLE_RUNS)))
def test_published_runs_replay_identically(name):
    from patterns.capability_aware_router.router import ReplayDecider
    rec = json.load(open(os.path.join(SAMPLE_RUNS, name)))
    replay = ReplayDecider([t["decision"] for t in rec["trace"]])
    r = run(rec["scenario"], approve=rec["approved"], use_bedrock=False, decider=replay)
    reasons = [t["decision"] and t["decision"]["reason"] for t in r["trace"]]
    assert reasons == [t["decision"] and t["decision"]["reason"] for t in rec["trace"]] and not replay.pending
    assert [t["tool"] for t in r["trace"]] == [t["tool"] for t in rec["trace"]]
    assert [t["decision"] and t["decision"]["route"] for t in r["trace"]] == \
           [t["decision"] and t["decision"]["route"] for t in rec["trace"]]
    assert r["outcome"] == rec["outcome"]
