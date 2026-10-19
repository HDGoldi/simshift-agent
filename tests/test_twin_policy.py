import pytest
import json

from simshift.policy import (counterfactual, exclusions, guarded_profile_transition, profile_transition_gate,
                             proposal_id)
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
    pid = twin.proposal_id("profile_B")
    a = twin.enable_profile("profile_B", pid)
    assert twin.enable_profile("profile_B", pid) is a and len(twin.events) == 1


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
    for wrong in (None, "k1", twin.proposal_id("profile_C")):
        res = twin.enable_profile("profile_B", wrong)
        assert not res["ok"] and twin.s["active_profile"] == "profile_A"
    assert twin.enable_profile("profile_B", twin.proposal_id("profile_B"))["ok"]  # refusals were not cached


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
    assert blocked == ["REQUESTED", "BLOCKED"] and "DELIVERED" not in blocked


def test_counterfactual_cannot_force_ota_on_offline():
    twin = FleetTwin("OFFLINE")
    cf = counterfactual(twin, "evaluate_profile_change")
    assert cf["excluded"] and cf["result"]["transition"] == ["REQUESTED", "BLOCKED"]
    assert "management_path_reachable" in cf["result"]["gate"]["failed"] and not twin.events  # real twin untouched


def test_counterfactual_shows_cost_of_wrong_choice():
    twin = FleetTwin("DE_OPERATOR")
    right, wrong = counterfactual(twin, "try_allowed_operator"), counterfactual(twin, "retry_connection")
    assert right["restored"] and not wrong["restored"] and not twin.events


def test_firmware_loop_is_not_fixed_by_the_network_side():
    twin = FleetTwin("FW_LOOP")
    twin.retry_with_backoff(); twin.retry_with_backoff()  # 4 of the 5 allowed
    assert not twin.service_restored()
    assert "reset loop" in twin.firmware_modem_diagnostics()["result"]["summary"]
    ex = exclusions(twin.observe())
    assert "evaluate_profile_change" in ex and "reset loop" in ex["retry_connection"]
    assert not guarded_profile_transition(twin, "profile_B", proposal_id(twin, "profile_B"))["executed"]


def test_transient_clears_on_retry_only():
    twin = FleetTwin("TRANSIENT")
    assert twin.observe()["attach_trend"] == "improving" and not twin.service_restored()
    twin.data_path_diagnostics(); twin.firmware_modem_diagnostics()
    assert not twin.service_restored()
    twin.retry_with_backoff()
    assert twin.service_restored() and twin.s["active_profile"] == "profile_A"


def test_lost_path_after_a_switch_rolls_back_on_the_device():  # audit T10, TEL-014
    twin = FleetTwin("TRANSIENT")  # management rides on cellular
    twin.s["networks"]["FR-NET-2"] = "down"
    ev = twin.enable_profile("profile_B", twin.proposal_id("profile_B"))  # direct eIM call, still registered
    assert ev["ok"] and not ev["result_reported"] and ev["rollback_authorized"]  # profile_B cannot report back
    assert twin.events[-1]["kind"] == "ipa_local_rollback" and twin.s["active_profile"] == "profile_A"
    assert not any(e["kind"] == "eim_rollback" for e in twin.events)  # the device did it, not an eIM command


def _br_switch(**changes):
    twin = FleetTwin("BR_PROFILE")
    for path, value in changes.items():
        *keys, last = path.split(".")
        d = twin.s
        for k in keys:
            d = d[k]
        d[last] = value
    twin.firmware_modem_diagnostics()
    return twin, guarded_profile_transition(twin, "profile_B", proposal_id(twin, "profile_B"))


def test_missing_result_is_never_read_as_success():  # audit T10, TEL-016
    twin, out = _br_switch(management_drops_on_switch=True)  # gateway lost mid-change; profile_B registers
    assert out["transition"][-3:] == ["RESULT_PENDING", "VERIFYING", "SUCCEEDED"]  # network sees profile_B's operator
    assert out["profile_state_evidence"]
    twin, out = _br_switch(management_drops_on_switch=True, **{"networks.BR-NET-2": "down"})
    assert out["transition"][-3:] == ["RESULT_PENDING", "VERIFYING", "UNCONFIRMED"] and "rollback" not in out
    kinds = [e["kind"] for e in twin.events]
    assert "ipa_local_rollback" in kinds and "eim_rollback" not in kinds  # no second command on a dead path


def test_reject_cause_stops_retries():  # audit T25, TEL-021
    twin = FleetTwin("BR_PROFILE")
    assert "retry_connection" not in exclusions(twin.observe())
    twin.firmware_modem_diagnostics()
    assert "network back-off" in exclusions(twin.observe())["retry_connection"]


def test_no_retry_for_devices_that_are_not_trying_to_attach():  # audit T18, TEL-028
    twin = FleetTwin("OFFLINE")
    assert "retry_connection" not in exclusions(twin.observe())
    d = twin.data_path_diagnostics()["result"]
    assert "PSM" in d["summary"] and "not trying to attach" in exclusions(twin.observe())["retry_connection"]


def test_reselection_stays_on_the_active_profile_list():  # audit T01/T02, TEL-001/002
    twin = FleetTwin("DE_OPERATOR")  # DE-NET-3 is in coverage but only on profile_B
    ev = twin.operator_reselection()
    assert ev["to_operator"] == "DE-NET-2" and twin.s["active_profile"] == "profile_A"
    twin = FleetTwin("DE_OPERATOR")
    twin.s["operators_in_coverage"].remove("DE-NET-2")
    assert "try_allowed_operator" in exclusions(twin.observe())  # a visible operator is not a permitted one


def test_no_alternate_profile_means_no_profile_change():  # audit T11
    twin = FleetTwin("BR_PROFILE")
    del twin.s["profiles"]["profile_B"]
    twin.firmware_modem_diagnostics()
    assert exclusions(twin.observe())["evaluate_profile_change"] == "no alternate profile installed"


def test_brazil_needs_a_path_that_does_not_ride_on_profile_a():  # audit P0 Brazil, TEL-022
    twin, out = _br_switch(**{"management.via_cellular": True})
    assert "evaluate_profile_change" in exclusions(twin.observe())
    assert not out["executed"] and "management_path_reachable" in out["gate"]["failed"]


def test_registered_without_a_data_session_is_not_restored(monkeypatch):  # audit T05, invariant 12
    twin = FleetTwin("JP_INGEST")
    monkeypatch.setattr(FleetTwin, "rates", lambda self: {"attach_success_rate": 0.997, "data_session_rate": 0.1,
                                                          "app_ack_rate": 0.995, "heartbeat_rate": 0.99})
    assert not twin.service_restored()


def test_firmware_cohort_is_not_offered_a_profile_change_first():  # audit T26, TEL-024
    twin = FleetTwin("FW_LOOP")
    assert "evaluate_profile_change" in exclusions(twin.observe())
    assert twin.firmware_modem_diagnostics()["result"]["same_cells_other_firmware"] == "stable"


def test_approval_for_a_stale_from_profile_is_refused():  # audit T27
    twin = FleetTwin("BR_PROFILE")
    twin.firmware_modem_diagnostics()
    stale = proposal_id(twin, "profile_B")  # issued while profile_A is active
    twin.s["active_profile"] = "profile_B"  # the device state moved on
    assert stale != proposal_id(twin, "profile_A")
    assert not profile_transition_gate(twin, "profile_A", stale)["checks"]["human_approval"]
    assert not twin.enable_profile("profile_A", stale)["ok"]


def test_eim_still_refuses_if_the_gate_were_broken(monkeypatch):
    from simshift import policy
    twin = FleetTwin("BR_PROFILE")
    real = policy.profile_transition_gate
    monkeypatch.setattr(policy, "profile_transition_gate",
                        lambda t, target, a: {**real(t, target, a), "allowed": True, "failed": []})  # broken gate
    out = policy.guarded_profile_transition(twin, "profile_B", None)  # no approval at all
    assert not out["executed"] and out["transition"][-1] == "NOT_DELIVERED"
    assert twin.s["active_profile"] == "profile_A" and "no operator approval" in out["eim"]["reason"]


@pytest.mark.parametrize("field", ["euicc.supports_profile_enable", "owner_allows_profile_switch"])
def test_eim_enforces_capability_and_owner_even_on_a_direct_call(field):
    twin = FleetTwin("BR_PROFILE")
    if "." in field:
        twin.s["euicc"]["supports_profile_enable"] = False
    else:
        twin.s[field] = False
    res = twin.enable_profile("profile_B", twin.proposal_id("profile_B"))  # bypasses the gate entirely
    assert not res["ok"] and twin.s["active_profile"] == "profile_A"


def test_restored_service_alone_does_not_confirm_a_missing_result(monkeypatch):  # adversarial review: TEL-016
    monkeypatch.setattr(FleetTwin, "service_restored", lambda self: True)  # telemetry looks fine either way
    twin = FleetTwin("BR_PROFILE")
    twin.s["management_drops_on_switch"] = True
    twin.s["profiles"]["profile_B"]["operators"] = ["BR-NET-3"]  # target operator never registers anywhere
    twin.s["operators_in_coverage"].append("BR-NET-3")
    twin.firmware_modem_diagnostics()
    out = guarded_profile_transition(twin, "profile_B", proposal_id(twin, "profile_B"))
    assert out["transition"][-1] == "UNCONFIRMED" and out["profile_state_evidence"] is None


def test_a_shared_operator_does_not_identify_the_target_profile(monkeypatch):  # Codex review pass 2
    from simshift import policy
    real = policy.profile_transition_gate  # the gate blocks this setup (reselection is available), so bypass it
    monkeypatch.setattr(policy, "profile_transition_gate",
                        lambda t, target, a: {**real(t, target, a), "allowed": True, "failed": []})
    twin = FleetTwin("BR_PROFILE")
    twin.s["management_drops_on_switch"] = True
    twin.s["profiles"]["profile_A"]["operators"] = ["BR-NET-1", "BR-NET-2"]  # both profiles reach BR-NET-2
    twin.firmware_modem_diagnostics()
    out = guarded_profile_transition(twin, "profile_B", proposal_id(twin, "profile_B"))
    assert twin.service_restored() and out["transition"][-1] == "UNCONFIRMED"  # service back, profile still unknown
    assert policy.only_on(twin.s["profiles"], "profile_B", "profile_A", "BR-NET-2") is False
