import json

from simshift.policy import exclusions, guarded_profile_transition, proposal_id
from simshift.simulator import SCENARIOS, FleetTwin


def test_policy_filters_unavailable_operator():
    twin = FleetTwin("BR_PROFILE")
    ex = exclusions(twin.observe())
    assert "try_allowed_operator" in ex and "modem evidence" in ex["evaluate_profile_change"]
    twin.firmware_modem_diagnostics()
    assert "evaluate_profile_change" not in exclusions(twin.observe())


def test_unreachable_blocks_ota():
    twin = FleetTwin("OFFLINE")
    assert "management path" in exclusions(twin.observe())["evaluate_profile_change"]
    forced = guarded_profile_transition(twin, "profile_B", proposal_id(twin, "profile_B"))  # even with approval
    assert not forced["executed"] and "management_path_reachable" in forced["gate"]["failed"]
    assert twin.s["active_profile"] == "profile_A"


def test_profile_requires_approval():
    twin = FleetTwin("BR_PROFILE")
    twin.firmware_modem_diagnostics()
    out = guarded_profile_transition(twin, "profile_B", None)
    assert not out["executed"] and out["gate"]["failed"] == ["human_approval"]
    assert twin.s["active_profile"] == "profile_A"


def test_brazil_recovery():
    twin = FleetTwin("BR_PROFILE")
    assert not twin.service_restored()
    twin.retry_with_backoff()
    assert not twin.service_restored()  # retrying the dead profile does not help
    assert not guarded_profile_transition(twin, "profile_B", proposal_id(twin, "profile_B"))["executed"]  # no evidence yet
    twin.firmware_modem_diagnostics()
    out = guarded_profile_transition(twin, "profile_B", proposal_id(twin, "profile_B"))
    r = twin.rates()
    assert out["verified_restored"] and r["attach_success_rate"] >= 0.95 and r["app_ack_rate"] >= 0.95


def test_japan_profile_change_not_offered_and_blocked():
    twin = FleetTwin("JP_INGEST")
    assert "causal path" in exclusions(twin.observe())["evaluate_profile_change"]
    out = guarded_profile_transition(twin, "profile_B", proposal_id(twin, "profile_B"))
    assert not out["executed"] and "active_profile_failing_registration" in out["gate"]["failed"]
    assert "ingest" in twin.data_path_diagnostics()["result"]["summary"]


def test_failed_verification_rolls_back():
    twin = FleetTwin("BR_PROFILE")
    twin.s["networks"]["BR-NET-2"] = "down"  # target profile's operator also dead
    twin.firmware_modem_diagnostics()
    out = guarded_profile_transition(twin, "profile_B", proposal_id(twin, "profile_B"))
    assert out["executed"] and not out["verified_restored"] and out["rollback"]["ok"]
    assert (twin.s["active_profile"], twin.s["serving_operator"]) == ("profile_A", "BR-NET-1")


def test_germany_operator_reselection():
    twin = FleetTwin("DE_OPERATOR")
    assert "try_allowed_operator" not in exclusions(twin.observe())
    ev = twin.operator_reselection()
    assert ev["restored"] and twin.s["active_profile"] == "profile_A"


def test_idempotent_enable():
    twin = FleetTwin("BR_PROFILE")
    a = twin.enable_profile("profile_B", "k1", approved=True)
    assert twin.enable_profile("profile_B", "k1", approved=True) is a and len(twin.events) == 1


def test_seed_reproducibility():
    def run(t):
        t.retry_with_backoff(); t.firmware_modem_diagnostics()
        guarded_profile_transition(t, "profile_B", proposal_id(t, "profile_B"))
        return t.observe(), t.events
    base = FleetTwin("BR_PROFILE")
    assert run(base.clone()) == run(base.clone()) == run(FleetTwin("BR_PROFILE"))


def test_no_truth_leakage():
    for sid, sc in SCENARIOS.items():
        twin = FleetTwin(sid)
        twin.firmware_modem_diagnostics(); twin.data_path_diagnostics()
        blob = json.dumps(twin.observe())
        assert sc["hidden"]["cause"] not in blob and "best_actions" not in blob and "networks" not in blob


def test_retry_after_rollback_really_executes():
    twin = FleetTwin("BR_PROFILE")
    twin.firmware_modem_diagnostics()
    twin.s["networks"]["BR-NET-2"] = "down"
    assert guarded_profile_transition(twin, "profile_B", proposal_id(twin, "profile_B"))["rollback"]["ok"]
    twin.s["networks"]["BR-NET-2"] = "up"
    out = guarded_profile_transition(twin, "profile_B", proposal_id(twin, "profile_B"))
    assert out["verified_restored"] and twin.s["active_profile"] == "profile_B"


def test_cellular_management_path_dies_with_registration():
    twin = FleetTwin("DE_OPERATOR")  # management rides on the failing cellular link
    obs = twin.observe()
    assert not obs["management_path_reachable"]
    assert "evaluate_profile_change" in exclusions(obs) and "investigate_device" in exclusions(obs)
    assert not guarded_profile_transition(twin, "profile_B", proposal_id(twin, "profile_B"))["executed"]


def test_profile_change_waits_for_reselection():
    twin = FleetTwin("DE_OPERATOR")
    twin.s["management"]["via_cellular"] = False  # even with a working management path
    twin.firmware_modem_diagnostics()
    assert "reselection comes first" in exclusions(twin.observe())["evaluate_profile_change"]
    gate = guarded_profile_transition(twin, "profile_B", proposal_id(twin, "profile_B"))["gate"]
    assert "no_operator_reselection_available" in gate["failed"]


def test_no_retry_when_registration_healthy():
    assert "retry_connection" in exclusions(FleetTwin("JP_INGEST").observe())


def test_eim_refuses_unapproved_enable():
    twin = FleetTwin("BR_PROFILE")
    res = twin.enable_profile("profile_B", "k1", approved=False)
    assert not res["ok"] and twin.s["active_profile"] == "profile_A"
    assert twin.enable_profile("profile_B", "k1", approved=True)["ok"]  # refusal was not cached


def test_approval_is_bound_to_one_proposal():
    twin = FleetTwin("BR_PROFILE")
    twin.firmware_modem_diagnostics()
    twin.s["networks"]["BR-NET-2"] = "down"
    approval = proposal_id(twin, "profile_B")
    assert not guarded_profile_transition(twin, "profile_C", approval)["executed"]  # not the approved target
    first = guarded_profile_transition(twin, "profile_B", approval)
    assert first["executed"] and first["transition"][-1] == "ROLLED_BACK"
    twin.s["networks"]["BR-NET-2"] = "up"
    again = guarded_profile_transition(twin, "profile_B", approval)  # same approval, after it was used
    assert not again["executed"] and again["gate"]["failed"] == ["human_approval"]
    assert guarded_profile_transition(twin, "profile_B", proposal_id(twin, "profile_B"))["verified_restored"]


def test_transition_timeline():
    br = FleetTwin("BR_PROFILE")
    br.firmware_modem_diagnostics()
    ok = guarded_profile_transition(br, "profile_B", proposal_id(br, "profile_B"))["transition"]
    assert ok.index("VERIFYING") < ok.index("SUCCEEDED") == len(ok) - 1
    off = FleetTwin("OFFLINE")
    blocked = guarded_profile_transition(off, "profile_B", proposal_id(off, "profile_B"))["transition"]
    assert blocked == ["REQUESTED", "BLOCKED"] and "SENT" not in blocked
