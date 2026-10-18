"""Digital twin tests: guarded outcomes, reproducibility, counterfactuals, no truth leakage."""

from __future__ import annotations

import json

import pytest

from agent.incident import Incident
from patterns.capability_aware_router import Decision
from simulator import scenarios
from simulator.twin import Twin, replay


class ScriptDecider:
    """Answers a fixed sequence; if the scripted option is not allowed, takes the first allowed."""

    def __init__(self, seq):
        self.seq, self.i = list(seq), 0

    def choose(self, state, question, criteria):
        want = self.seq[self.i] if self.i < len(self.seq) else None
        self.i += 1
        c = want if want in criteria else next(iter(criteria))
        return Decision(choice=c, probabilities={c: 0.6}, confidence=0.4, model="script")


def yes(_t, _p):
    return True


# ---------------------------------------------------------------- Brazil
def test_brazil_recovery_needs_approval_and_restores_both_layers():
    out = Incident("profile_recovery", ScriptDecider(["evaluate_profile_change"]), approve=yes).run()
    o = out["outcome"]
    assert o["restored"] and o["resolution"] == "profile_switch"
    assert o["registration_rate"] >= 0.95 and o["application_ack_rate"] >= 0.95
    assert o["profile_changes"] == 1 and o["unnecessary_profile_changes"] == 0
    tl = out["steps"][0]["profile_execution"]["timeline"]
    assert any("eUICC" in x for x in tl) and any("telemetry acknowledged" in x for x in tl)


def test_brazil_without_approval_changes_nothing():
    out = Incident("profile_recovery", ScriptDecider(["evaluate_profile_change", "escalate_or_wait"])).run()
    o = out["outcome"]
    assert not o["restored"] and o["profile_changes"] == 0
    assert out["steps"][0]["approval"] == "not approved"
    assert out["steps"][0]["profile_execution"]["blocked_reasons"] == ["not approved"]


# ---------------------------------------------------------------- Offline
def test_offline_forced_profile_change_is_blocked():
    t = Twin.from_scenario("unreachable_device")
    t.obs["profile_change_pending"] = True  # pretend someone forced a plan in
    res = t.execute_profile_change(approved=True)
    assert res["executed"] is False and "no reachable management path" in res["blocked_reasons"]
    assert t.outcome()["profile_changes"] == 0 and t.outcome()["blocked_actions"] == 1


def test_offline_escalates_without_remote_change():
    out = Incident("unreachable_device", ScriptDecider(["escalate_or_wait"]), approve=yes).run()
    o = out["outcome"]
    assert o["escalated"] and not o["restored"] and o["profile_changes"] == 0


# ---------------------------------------------------------------- Japan
def test_japan_data_path_then_escalation_restores_without_profile_change():
    out = Incident("application_failure", ScriptDecider(["investigate_data_path", "escalate_or_wait"]),
                   approve=yes).run()
    o = out["outcome"]
    assert o["restored"] and o["resolution"] == "application_team_fix" and o["profile_changes"] == 0
    # after the finding, policy removes the profile option
    assert out["steps"][1]["removed"]["evaluate_profile_change"].startswith("diagnostics place the fault")


def test_japan_counterfactual_profile_switch_is_unnecessary():
    cf = replay("application_failure", ["evaluate_profile_change"], approve=True)
    o = cf["outcome"]
    assert o["profile_changes"] == 1 and o["unnecessary_profile_changes"] == 1 and not o["restored"]


def test_brazil_counterfactual_retries_do_not_help():
    o = replay("profile_recovery", ["retry_connection", "retry_connection"])["outcome"]
    assert not o["restored"] and o["downtime_minutes"] == 30


# ---------------------------------------------------------------- general
@pytest.mark.parametrize("name", scenarios.names())
def test_seed_reproducibility(name):
    seq = ["investigate_data_path", "evaluate_profile_change", "escalate_or_wait"]
    assert replay(name, seq, seed=3) == replay(name, seq, seed=3)


@pytest.mark.parametrize("name", scenarios.names())
def test_twin_never_leaks_truth(name):
    hidden = scenarios.load(name)["evaluator_only"]["true_cause"]
    out = replay(name, ["investigate_device", "investigate_data_path", "evaluate_profile_change",
                        "retry_connection", "escalate_or_wait"])
    t = Twin.from_scenario(name)
    blob = json.dumps(out) + json.dumps(t.observe()) + scenarios.describe(t.observe())
    assert hidden not in blob


def test_forbidden_executions_always_zero():
    for name in scenarios.names():
        for seq in (["evaluate_profile_change"], ["escalate_or_wait"], ["retry_connection"]):
            assert replay(name, seq)["outcome"]["forbidden_executions"] == 0
