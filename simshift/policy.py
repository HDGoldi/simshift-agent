"""Deterministic capability filter and profile-transition gate. No model output can bypass these."""
from __future__ import annotations

from .simulator import RESTORED_THRESHOLD, FleetTwin, idempotency_key

MAX_RETRIES = 5
MAX_RESETS_PER_DAY = 5  # above this the fault is on the device, not the network

# Option -> description shown to Decider. Says when each tool fits; never mentions hidden truth.
OPTIONS = {
    "retry_connection": "Bounded backoff and re-attach on the current profile and operator; suits brief or improving disruptions",
    "try_allowed_operator": "Reselect another operator the ACTIVE profile already permits (no profile change); suits a failing serving network",
    "investigate_device": "Read-only: pull modem and firmware diagnostics from the devices",
    "investigate_data_path": "Read-only: check network-side data sessions, APN and application ingestion; suits devices that register but whose telemetry fails",
    "evaluate_profile_change": "Assess a managed switch to an installed alternate eSIM profile (does not execute it); suits an active profile that cannot register on any allowed operator",
    "escalate_or_wait": "Hold and hand off to a human with the collected evidence; suits cases no admissible remote action can fix",
}
READ_ONLY = frozenset({"investigate_device", "investigate_data_path"})
FALLBACK = "escalate_or_wait"


def exclusions(obs: dict) -> dict[str, str]:
    """Options that are inadmissible in this state, with the reason. Excluded options are never offered."""
    out: dict[str, str] = {}
    if obs["attempted_retries"] >= MAX_RETRIES:
        out["retry_connection"] = f"retry budget exhausted ({MAX_RETRIES})"
    elif obs["attach_success_rate"] >= RESTORED_THRESHOLD:
        out["retry_connection"] = "registration already healthy; re-attaching cannot help"
    elif obs["diagnostics"].get("device", {}).get("modem_resets_per_day", 0) > MAX_RESETS_PER_DAY:
        out["retry_connection"] = "modem reset loop on the devices; re-attaching cannot help"
    if not obs["other_operator_allowed_on_active_profile"]:
        out["try_allowed_operator"] = "active profile permits no other operator in coverage"
    if not obs["management_path_reachable"]:
        out["investigate_device"] = "devices unreachable; no modem logs retrievable"
        out["evaluate_profile_change"] = "no management path to the IPA; OTA profile change impossible"
    elif not obs["alternative_profile_installed"]:
        out["evaluate_profile_change"] = "no alternate profile installed"
    elif obs["other_operator_allowed_on_active_profile"]:
        out["evaluate_profile_change"] = "active profile still permits another operator; reselection comes first"
    elif obs["attach_success_rate"] >= RESTORED_THRESHOLD:
        out["evaluate_profile_change"] = (f"active profile registers normally ({obs['attach_success_rate']:.1%});"
                                          " a profile switch has no causal path to recovery")
    elif not obs["diagnostics"].get("device", {}).get("reject_cause"):
        out["evaluate_profile_change"] = "needs modem evidence (registration reject cause) before a profile switch"
    for name, key in (("investigate_device", "device"), ("investigate_data_path", "data_path")):
        if key in obs["diagnostics"] and name not in out:
            out[name] = "evidence already collected"
    return out


# Allowed eUICC transition paths. Verification always precedes SUCCEEDED; a blocked request is never SENT.
TRANSITION_PATHS = {
    ("REQUESTED", "BLOCKED"),
    ("REQUESTED", "VALIDATED", "APPROVED", "NOT_DELIVERED"),
    ("REQUESTED", "VALIDATED", "APPROVED", "SENT", "ACK", "ENABLED", "VERIFYING", "SUCCEEDED"),
    ("REQUESTED", "VALIDATED", "APPROVED", "SENT", "ACK", "ENABLED", "VERIFYING", "FAILED", "ROLLED_BACK"),
    ("REQUESTED", "VALIDATED", "APPROVED", "SENT", "ACK", "ENABLED", "VERIFYING", "FAILED", "ROLLBACK_FAILED"),
}


def proposal_id(twin: FleetTwin, target: str) -> str:
    """Identifies one proposed switch: cohort, from, to, and how many switches already ran. An approval is
    bound to this id, so it cannot be reused for another target or after the switch it approved has run."""
    return f"{idempotency_key(twin.scenario_id, twin.s['active_profile'], target)}.{twin.profile_changes}"


def profile_transition_gate(twin: FleetTwin, target: str, approval: str | None) -> dict:
    """Hard checks before the virtual eIM may enable `target`. Returns every check and the verdict."""
    s = twin.s
    target_ops = s["profiles"].get(target, {}).get("operators", [])
    pid = proposal_id(twin, target)
    checks = {
        "euicc_supports_profile_enable": s["euicc"]["supports_profile_enable"],
        "active_profile_failing_registration": twin.rates()["attach_success_rate"] < RESTORED_THRESHOLD,
        "registration_reject_evidence": bool(twin.diagnostics.get("device", {}).get("reject_cause")),
        "no_operator_reselection_available": not any(
            o != s["serving_operator"] and o in s["operators_in_coverage"]
            for o in s["profiles"][s["active_profile"]]["operators"]),
        "target_installed_and_not_active": target in s["profiles"] and target != s["active_profile"],
        "target_operator_in_coverage": any(o in s["operators_in_coverage"] for o in target_ops),
        "management_path_reachable": twin.management_reachable(),
        "owner_authorizes_profile_switch": s["owner_allows_profile_switch"],
        "human_approval": approval == pid,  # bound to this exact proposal
    }
    failed = [k for k, ok in checks.items() if not ok]
    return {"target": target, "proposal_id": pid, "checks": checks, "allowed": not failed, "failed": failed}


def guarded_profile_transition(twin: FleetTwin, target: str, approval: str | None) -> dict:
    """Gate -> virtual eIM enable -> verify registration AND app telemetry -> rollback if verification fails."""
    gate = profile_transition_gate(twin, target, approval)
    if not gate["allowed"]:
        return _done({"executed": False, "gate": gate}, ["REQUESTED", "BLOCKED"])
    previous, previous_operator = twin.s["active_profile"], twin.s["serving_operator"]
    result = twin.enable_profile(target, gate["proposal_id"], approved=True)
    if not result.get("ok"):
        return _done({"executed": False, "gate": gate, "eim": result}, ["REQUESTED", "VALIDATED", "APPROVED", "NOT_DELIVERED"])
    states = ["REQUESTED", "VALIDATED", "APPROVED", "SENT", "ACK", "ENABLED", "VERIFYING"]
    verified = twin.service_restored()
    out = {"executed": True, "gate": gate, "eim": result, "verified_restored": verified}
    if verified:
        return _done(out, states + ["SUCCEEDED"])
    out["rollback"] = twin.rollback_profile(previous, previous_operator)
    return _done(out, states + ["FAILED", "ROLLED_BACK" if out["rollback"]["ok"] else "ROLLBACK_FAILED"])


def _done(out: dict, states: list[str]) -> dict:
    if tuple(states) not in TRANSITION_PATHS:
        raise RuntimeError(f"illegal eUICC transition path {states}")
    return {**out, "transition": states}


def counterfactual(twin: FleetTwin, option: str) -> dict:
    """What `option` would have done from this state, run on a clone; the real twin is untouched. Policy
    exclusions are reported but not enforced, so a rejected option can be shown failing. A profile change
    still goes through the full gate (approval is granted on the clone only), so it can never be forced."""
    c = twin.clone()
    actions = {"retry_connection": c.retry_with_backoff, "try_allowed_operator": c.operator_reselection,
               "investigate_device": c.firmware_modem_diagnostics, "investigate_data_path": c.data_path_diagnostics,
               "escalate_or_wait": c.escalate}
    if option == "evaluate_profile_change":
        target = next(p for p in c.s["profiles"] if p != c.s["active_profile"])
        result = guarded_profile_transition(c, target, proposal_id(c, target))
    else:
        result = actions[option]()
    return {"option": option, "excluded": exclusions(twin.observe()).get(option), "result": result,
            "restored": c.service_restored(), "rates": c.rates(), "simulated_minutes": c.simulated_minutes()}
