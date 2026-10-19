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
        for secret in (sc["hidden"]["cause"], sid, "best_actions", '"networks"', "ingestion_healthy",
                       "firmware_fault", "transient_congestion", "management_drops_on_switch"):
            assert secret not in sent, (sid, secret)


def _decider_up(url):
    try:
        return json.load(urllib.request.urlopen(f"{url}/health", timeout=2))["status"] == "ok"
    except OSError:
        return False


URL = os.environ.get("DECIDER_URL", "http://127.0.0.1:8099")


# Skips without a server, unless SIMSHIFT_REQUIRE_DECIDER=1: then a missing Decider is a failure, not a skip.
@pytest.mark.skipif(not _decider_up(URL) and os.environ.get("SIMSHIFT_REQUIRE_DECIDER") != "1",
                    reason="Decider server not running")
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
                       "device_powered", '"hidden"', "firmware_fault", "transient_congestion",
                       "management_drops_on_switch"):
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


@pytest.mark.parametrize("name", sorted(f for d in ("", "orchestrated") for f in
                                         (os.path.join(d, x) for x in os.listdir(os.path.join(SAMPLE_RUNS, d)))
                                         if f.endswith(".json")))
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
    assert {k: r["outcome"][k] for k in rec["outcome"]} == rec["outcome"]  # newer runs record more fields


def test_audit_counts_a_forbidden_execution_when_the_gate_is_missing():
    from strands import Agent
    from strands.models import BedrockModel

    from simshift.agent import audit_counts, build_tools, watch_tool_calls
    from simshift.simulator import FleetTwin
    twin = FleetTwin("OFFLINE")  # investigate_device is excluded: devices unreachable
    gated = run("OFFLINE", decider=ScriptedDecider(["investigate_data_path"]), use_bedrock=False)
    assert gated["outcome"]["forbidden_executions"] == 0
    bare = Agent(model=BedrockModel(model_id="unused", region_name="us-east-1"),
                 tools=build_tools(twin, lambda pid: False, None), callback_handler=None)  # no policy gate
    audit = watch_tool_calls(bare, twin)
    bare.tool.query_firmware_modem_diagnostics()
    assert audit_counts(audit) == {"forbidden_executions": 1, "blocked_calls": 0}


def test_gate_denial_is_counted_as_blocked():
    from simshift.agent import audit_counts, build_tools, make_router, watch_tool_calls
    from simshift.simulator import FleetTwin
    from strands import Agent
    from strands.models import BedrockModel
    twin = FleetTwin("OFFLINE")
    agent = Agent(model=BedrockModel(model_id="unused", region_name="us-east-1"), tools=build_tools(twin, lambda pid: True, None),
                  interventions=[make_router(None).gate(twin.observe)], callback_handler=None)
    audit = watch_tool_calls(agent, twin)
    res = agent.tool.prepare_guarded_profile_transition()
    assert res["status"] == "error" and audit_counts(audit) == {"forbidden_executions": 0, "blocked_calls": 1}
    assert not any(e["kind"].startswith("eim_") for e in twin.events)


def test_deferred_approval():
    from simshift.agent import Incident
    from simshift.validate import problems
    for approve in (True, False):
        inc = Incident("BR_PROFILE", decider=ScriptedDecider(["investigate_device", "evaluate_profile_change"]),
                       use_bedrock=False)
        while not inc.done:
            inc.step()
        pid = inc.pending_approval
        assert pid and inc.twin.s["active_profile"] == "profile_A"
        last = inc.resolve_approval(approve)
        assert inc.done and inc.pending_approval is None and pid in last["note"]
        assert inc.twin.service_restored() == approve and problems(inc.result()) == []


def _br_variant(monkeypatch, **changes):
    import copy

    from simshift.simulator import SCENARIOS
    sc = copy.deepcopy(SCENARIOS["BR_PROFILE"])
    for path, value in changes.items():
        *keys, last = path.split(".")
        d = sc
        for k in keys:
            d = d[k]
        d[last] = value
    monkeypatch.setitem(SCENARIOS, "BR_VARIANT", sc)
    return "BR_VARIANT"


@pytest.mark.parametrize("changes, end", [
    ({"networks.BR-NET-2": "down"}, "ROLLED_BACK"),  # verification fails, rollback works
    ({"euicc.rollback_supported": False}, "BLOCKED"),  # never switch without a way back
    ({"owner_allows_profile_switch": False}, "BLOCKED"),  # a gate check the policy filter does not mirror
])
def test_failed_profile_change_escalates(monkeypatch, changes, end):
    sid = _br_variant(monkeypatch, **changes)
    r = run(sid, approve=True, decider=ScriptedDecider(["investigate_device", "evaluate_profile_change"]),
            use_bedrock=False)
    change = next(t for t in r["trace"] if t["tool"] == TOOLS["evaluate_profile_change"])
    assert change["tool_result"]["transition"][-1] == end
    assert r["trace"][-1]["tool"] == TOOLS["escalate_or_wait"] and end in r["trace"][-1]["note"]
    assert any(e["kind"] == "escalated" for e in r["events"])
    if end == "BLOCKED" and "euicc.rollback_supported" in changes:
        assert "rollback_supported" in change["tool_result"]["gate"]["failed"]


def test_rollback_failure_escalates(monkeypatch):
    from simshift.simulator import FleetTwin
    sid = _br_variant(monkeypatch, **{"networks.BR-NET-2": "down"})
    monkeypatch.setattr(FleetTwin, "rollback_profile",  # e.g. the eUICC refuses the re-enable
                        lambda self, prev, op: self._log("eim_rollback", ok=False, reason="IPA unreachable"))
    r = run(sid, approve=True, decider=ScriptedDecider(["investigate_device", "evaluate_profile_change"]),
            use_bedrock=False)
    change = next(t for t in r["trace"] if t["tool"] == TOOLS["evaluate_profile_change"])
    assert change["tool_result"]["transition"][-1] == "ROLLBACK_FAILED"
    assert r["outcome"]["active_profile"] == "profile_B" and not r["outcome"]["restored"]
    assert "ROLLBACK_FAILED" in r["trace"][-1]["note"] and any(e["kind"] == "escalated" for e in r["events"])


def test_bedrock_review_failure_still_reaches_the_gate(monkeypatch):
    import simshift.agent as ag

    def broken(llm, prompt, schema=None):
        raise RuntimeError("throttled")
    monkeypatch.setattr(ag, "_bedrock", broken)
    inc = ag.Incident("BR_PROFILE", decider=ScriptedDecider(["investigate_device", "evaluate_profile_change"]))
    while not inc.done:
        inc.step()
    assert inc.pending_approval and "throttled" in inc.trace[-1]["tool_result"]["bedrock_plan"]["error"]
    inc.resolve_approval(True)
    assert inc.twin.service_restored()


def test_human_answers_are_recorded_and_replayed():
    from patterns.capability_aware_router.router import ReplayDecider
    from simshift.agent import Incident, finish, recorded_answers
    for approve in (True, False):
        inc = Incident("BR_PROFILE", decider=ScriptedDecider(["investigate_device", "evaluate_profile_change"]),
                       use_bedrock=False)
        finish(inc, lambda pid, gate: approve)
        rec = json.loads(json.dumps(inc.result()))
        assert rec["approved"] is False and rec["human_answers"] == {inc.trace[1]["tool_result"]["gate"]["proposal_id"]: approve}
        again = Incident("BR_PROFILE", decider=ReplayDecider([t["decision"] for t in rec["trace"]]), use_bedrock=False)
        finish(again, recorded_answers(rec))
        assert [t["tool"] for t in again.trace] == [t["tool"] for t in rec["trace"]]
        assert again.twin.service_restored() == approve


def test_cli_printer_handles_a_failed_bedrock_review(monkeypatch, capsys):
    import simshift.agent as ag
    monkeypatch.setattr(ag, "_bedrock", lambda llm, prompt, schema=None: (_ for _ in ()).throw(RuntimeError("down")))
    r = ag.run("BR_PROFILE", approve=True, decider=ScriptedDecider(["investigate_device", "evaluate_profile_change"]))
    ag._print(r, "test")
    assert "Bedrock review unavailable" in capsys.readouterr().out


def test_unconfirmed_switch_is_handed_off_without_a_second_command(monkeypatch):  # audit T10
    from simshift.validate import problems
    sid = _br_variant(monkeypatch, **{"networks.BR-NET-2": "down", "management_drops_on_switch": True})
    r = run(sid, approve=True, decider=ScriptedDecider(["investigate_device", "evaluate_profile_change"]),
            use_bedrock=False)
    change = next(t for t in r["trace"] if t["tool"] == TOOLS["evaluate_profile_change"])
    assert change["tool_result"]["transition"][-1] == "UNCONFIRMED"
    assert "UNCONFIRMED" in r["trace"][-1]["note"] and r["trace"][-1]["tool"] == TOOLS["escalate_or_wait"]
    kinds = [e["kind"] for e in r["events"]]
    assert "ipa_local_rollback" in kinds and "eim_rollback" not in kinds
    assert r["outcome"]["active_profile"] == "profile_A" and problems(r) == []  # outcome reports the real state


def test_cli_prints_each_step_before_the_approval_prompt(tmp_path):
    """The operator sees the evidence and the gate before being asked to approve."""
    import os
    import pty
    import subprocess
    import sys
    from simshift.agent import Incident, write_trace
    inc = Incident("BR_PROFILE", decider=ScriptedDecider(["investigate_device", "evaluate_profile_change"]),
                   use_bedrock=False)
    while not inc.done:
        inc.step()
    rec = tmp_path / "pending.json"
    write_trace(str(rec), inc.result())  # ends pending; the replay asks the terminal again
    master, slave = pty.openpty()
    p = subprocess.Popen([sys.executable, "-m", "simshift.agent", "BR_PROFILE", "--no-bedrock", "--replay", str(rec)],
                         stdin=slave, stdout=slave, stderr=slave, cwd=os.path.dirname(os.path.dirname(__file__)))
    os.close(slave)
    out = b""
    while b"[y/N]" not in out:
        chunk = os.read(master, 4096)
        assert chunk, out
        out += chunk
    os.write(master, b"n\n")
    p.wait(timeout=30)
    text = out.decode()
    assert text.index("[2]") < text.index("-> tool prepare_guarded_profile_transition") < text.index("[y/N]")


def test_a_malformed_answer_cannot_stop_the_cli_before_the_trace_is_written(capsys):  # Codex review
    import simshift.agent as ag
    bad = {"step": 1, "tool": "defer_or_escalate", "tool_status": "success", "tool_result": {},
           "decision": {"raw": {"choice": "x", "probabilities": {"x": "0.9"}, "confidence": "high"},
                        "excluded": {}, "route": "fallback", "reason": "inconsistent Decider answer"}}
    ag._print_step_safely(bad)  # the plain printer would raise on the string values
    assert "could not print this step" in capsys.readouterr().out
