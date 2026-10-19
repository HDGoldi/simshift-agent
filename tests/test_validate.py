import copy
import glob
import json
import os

import pytest

from simshift.simulator import SCENARIOS
from simshift.validate import problems

RUNS = sorted(glob.glob(os.path.join(os.path.dirname(__file__), "..", "docs", "sample-runs", "**", "*.json"),
                        recursive=True))


def load(name):
    return json.load(open([p for p in RUNS if p.endswith(f"orchestrated/{name}.json")][0]))


def test_published_runs_are_valid():
    assert RUNS
    for path in RUNS:
        assert problems(json.load(open(path))) == [], path


def at(run, tool):
    """The first step that ran `tool`, so tamper cases survive a re-recorded run with a different length."""
    return next(t for t in run["trace"] if t["tool"] == tool)


SWITCH = "prepare_guarded_profile_transition"


def tamper(name, fn):
    run = copy.deepcopy(load(name))
    fn(run)
    return run


@pytest.mark.parametrize("name, fn, expected", [
    ("OFFLINE", lambda r: r["outcome"].update(restored=True), "claims restored"),
    ("OFFLINE", lambda r: r["outcome"].update(restored=True, final_rates={k: 0.99 for k in r["outcome"]["final_rates"]}),
     "outcome rates differ"),  # Codex pass 5: rates rewritten to match the claim
    ("OFFLINE", lambda r: [r["outcome"].update(restored=True, final_rates={k: 0.99 for k in r["outcome"]["final_rates"]}),
                           r["trace"][-1].update(rates_after=dict(r["outcome"]["final_rates"]))],
     "does not reproduce"),  # Codex pass 6: rates edited consistently, but no action produced them
    ("OFFLINE", lambda r: r["outcome"].update(active_profile="profile_B", profile_changes=1),
     "does not reproduce"),  # Codex pass 6: a switch with no profile event
    ("BR_PROFILE", lambda r: r["trace"][0].update(tool="simulate_retry_with_backoff"), "not the routed admissible"),
    ("BR_PROFILE", lambda r: at(r, SWITCH)["tool_result"]["gate"].update(allowed=False), "passing gates"),
    ("BR_PROFILE", lambda r: r["trace"][0]["decision"]["raw"].update(confidence=0.9), "inconsistent"),
    ("BR_PROFILE", lambda r: r["trace"][0]["decision"]["state"].update(x=SCENARIOS["BR_PROFILE"]["hidden"]["cause"]),
     "hidden cause leaked"),
    ("BR_PROFILE", lambda r: (s := at(r, SWITCH))["decision"].update(selected="escalate_or_wait")
     or s.update(tool="defer_or_escalate"), "route act but"),
    ("BR_PROFILE", lambda r: r.update(approved=False), "without a recorded human approval"),
    ("BR_PROFILE", lambda r: r.update(approved="false"), "without a recorded human approval"),  # truthy is not True
    ("OFFLINE", lambda r: r["trace"][-1].update(decision=None, tool="simulate_retry_with_backoff", note="x"),
     "without a decision"),
    ("OFFLINE", lambda r: r["trace"][0]["decision"]["excluded"].pop("evaluate_profile_change"), "policy gives"),
    ("OFFLINE", lambda r: r["outcome"].update(forbidden_executions=1), "forbidden executions"),
    ("OFFLINE", lambda r: r["trace"].append({**r["trace"][-1], "step": 9, "decision": None, "note": "operator approved x",
                                             "tool": "prepare_guarded_profile_transition"}), "pending proposal"),
])
def test_validator_catches_each_kind_of_tampering(name, fn, expected):
    found = problems(tamper(name, fn))
    assert any(expected in p for p in found), found


def test_validator_requires_a_handoff_after_a_failed_profile_change(monkeypatch):
    import copy as cp

    from simshift.agent import run
    from tests.test_agent import ScriptedDecider
    sc = cp.deepcopy(SCENARIOS["BR_PROFILE"])
    sc["owner_allows_profile_switch"] = False
    monkeypatch.setitem(SCENARIOS, "BR_NO_OWNER", sc)
    r = run("BR_NO_OWNER", approve=True, decider=ScriptedDecider(["investigate_device", "evaluate_profile_change"]),
            use_bedrock=False)
    assert problems(r) == []
    silent = cp.deepcopy(r)
    silent["trace"].pop()  # drop the handoff: the run now ends at BLOCKED
    assert any("must be followed by a handoff" in p for p in problems(silent))
    assert any("ends without" in p for p in problems(silent))


def test_validator_checks_human_answers_against_the_trace(monkeypatch):
    from simshift.agent import Incident, finish
    from tests.test_agent import ScriptedDecider
    for approve in (True, False):
        inc = Incident("BR_PROFILE", decider=ScriptedDecider(["investigate_device", "evaluate_profile_change"]),
                       use_bedrock=False)
        finish(inc, lambda pid, gate: approve)
        r = json.loads(json.dumps(inc.result()))
        assert problems(r) == []
        r["human_answers"] = {}  # strip the answer the approve/decline step relies on
        assert any("does not match the recorded human answers" in p for p in problems(r))
        if approve:
            assert any("without a recorded human approval" in p for p in problems(r))


@pytest.mark.parametrize("name, enable_fields, rollback", [
    ("OFFLINE", {}, ("profile_B", "profile_A")),  # no enable at all
    ("BR_PROFILE", {"rollback_authorized": False, "result_reported": False}, ("profile_B", "profile_A")),
    ("BR_PROFILE", {}, ("profile_B", "profile_A")),  # the enable reported its result: nothing to roll back locally
    ("BR_PROFILE", {"result_reported": False}, ("profile_A", "profile_B")),  # does not undo that enable
])
def test_validator_rejects_a_local_rollback_that_does_not_fit(name, enable_fields, rollback):
    run = copy.deepcopy(load(name))
    enable = next((e for e in run["events"] if e["kind"] == "eim_enable_profile"), {})
    enable.update(enable_fields)
    run["events"].append({"seq": len(run["events"]) + 1, "kind": "ipa_local_rollback",
                          "from_profile": rollback[0], "to_profile": rollback[1]})
    assert any("local rollback without" in p for p in problems(run))


def test_validator_accepts_the_local_rollback_the_twin_produces(monkeypatch):
    from simshift.agent import run as run_incident
    from tests.test_agent import ScriptedDecider, _br_variant
    sid = _br_variant(monkeypatch, **{"networks.BR-NET-2": "down", "management_drops_on_switch": True})
    r = run_incident(sid, approve=True, decider=ScriptedDecider(["investigate_device", "evaluate_profile_change"]),
                     use_bedrock=False)
    assert any(e["kind"] == "ipa_local_rollback" for e in r["events"]) and problems(r) == []


def _unreport(run):
    """Marks BR's switch as unreported in both the event and the tool result, as a tamperer would."""
    for e in run["events"]:
        if e["kind"] == "eim_enable_profile":
            e["result_reported"] = False
    for t in run["trace"]:
        if t["tool"] == SWITCH and isinstance(t["tool_result"], dict) and "eim" in t["tool_result"]:
            t["tool_result"]["eim"]["result_reported"] = False


def test_validator_rejects_a_success_path_the_eim_result_contradicts():  # Codex adversarial pass 2
    run = copy.deepcopy(load("BR_PROFILE"))
    _unreport(run)  # path still says RESULT_REPORTED -> SUCCEEDED
    assert any("does not follow from the event log" in p for p in problems(run))


def _switch_step(run):
    return next(t for t in run["trace"] if isinstance(t["tool_result"], dict) and t["tool_result"].get("executed"))


@pytest.mark.parametrize("fn, expected", [  # Codex adversarial pass 3
    (lambda r: next(e for e in r["events"] if e["kind"] == "eim_enable_profile").update(result_reported=False),
     "does not match the event log"),  # the event log changed, the tool result did not
    (lambda r: _switch_step(r)["tool_result"].update(
        transition=_switch_step(r)["tool_result"]["transition"][:-1] + ["FAILED", "ROLLED_BACK"]),
     "does not follow from the event log"),  # a rollback with no rollback event
    (lambda r: _switch_step(r)["tool_result"]["gate"]["checks"].update(human_approval=False),
     "gate verdict does not follow"),
    (lambda r: _switch_step(r)["tool_result"]["gate"].update(proposal_id="0000000000000000.0"),
     "proposal id does not match"),
    (lambda r: _switch_step(r)["tool_result"]["gate"].update(target="profile_A"),  # Codex pass 4
     "do not match"),
    (lambda r: [e["rates"].update(data_session_rate=0.0) for e in r["events"] if e["kind"] == "eim_enable_profile"]
     and _switch_step(r)["tool_result"]["eim"]["rates"].update(data_session_rate=0.0),  # Codex pass 4
     "does not follow from the event log"),
])
def test_validator_reconciles_switches_with_the_event_log(fn, expected):
    run = copy.deepcopy(load("BR_PROFILE"))
    fn(run)
    assert any(expected in p for p in problems(run)), problems(run)


def test_validator_rejects_a_local_rollback_the_outcome_ignores():  # Codex adversarial pass 2
    run = copy.deepcopy(load("BR_PROFILE"))
    _unreport(run)
    run["events"].append({"seq": len(run["events"]) + 1, "kind": "ipa_local_rollback",
                          "from_profile": "profile_B", "to_profile": "profile_A"})
    assert any("profile events end on profile_A" in p for p in problems(run))  # outcome still claims profile_B


def test_validator_rejects_a_rollback_to_the_wrong_profile(monkeypatch):  # Codex adversarial pass 5
    from simshift.agent import run as run_incident
    from tests.test_agent import ScriptedDecider, _br_variant
    sid = _br_variant(monkeypatch, **{"networks.BR-NET-2": "down"})  # verification fails, eIM rolls back to profile_A
    r = run_incident(sid, approve=True, decider=ScriptedDecider(["investigate_device", "evaluate_profile_change"]),
                     use_bedrock=False)
    assert problems(r) == []
    bad = copy.deepcopy(r)
    rb = next(e for e in bad["events"] if e["kind"] == "eim_rollback")
    rb["to_profile"] = "profile_B"  # "rolls back" onto the profile that just failed
    next(t for t in bad["trace"] if isinstance(t["tool_result"], dict) and "rollback" in t["tool_result"]
         )["tool_result"]["rollback"]["to_profile"] = "profile_B"
    bad["outcome"]["active_profile"] = "profile_B"
    assert any("does not follow from the event log" in p for p in problems(bad))
