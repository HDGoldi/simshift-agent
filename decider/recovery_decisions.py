"""SIMShift's use of the Capability-Aware Router: the typed question, options and policy."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from agent import tools
from patterns.capability_aware_router import (
    CapabilityAwareRouter,
    DeciderClient,
    Option,
    Rule,
    RulePolicy,
)
from simulator.scenarios import describe

QUESTION = (
    "Given the current cellular connectivity symptoms, existing diagnostic evidence, and "
    "admissible tools, which next tool is most useful for safely advancing service restoration? "
    "Do not assume that an unverified recovery path works."
)

# name -> (description sent to Decider, default stub tool)
OPTION_SPECS: dict[str, tuple[str, Callable[[Any], Any]]] = {
    "retry_connection": (
        "bounded backoff and retry on the current subscription; fits brief, improving disruptions",
        tools.simulate_retry_with_backoff),
    "try_allowed_operator": (
        "attach to another network that the active profile already permits; no profile change",
        tools.simulate_operator_reselection),
    "investigate_device": (
        "read-only modem and firmware diagnostics; fits device resets or firmware cohorts",
        tools.query_firmware_modem_diagnostics),
    "investigate_data_path": (
        ("read-only APN, data session and application ingestion diagnostics; fits devices that are "
        "registered but whose data is not arriving"),
        tools.query_apn_session_app_diagnostics),
    "evaluate_profile_change": (
        "check feasibility of enabling a different installed eSIM profile; does not execute it",
        tools.prepare_guarded_profile_transition),
    "escalate_or_wait": (
        ("hold and hand to a human team; fits cases where no remote action can reach the devices, "
        "or the root cause is outside the cellular layer"),
        tools.defer_or_escalate),
}

OPTIONS = [Option(n, d, t) for n, (d, t) in OPTION_SPECS.items()]


def _done(option: str) -> Callable[[Mapping[str, Any]], bool]:
    return lambda s: option in s.get("steps_taken", [])


POLICY = RulePolicy([
    Rule("try_allowed_operator", lambda s: not s["allowed_alternative_operator_available"],
         "no permitted alternate operator on the active profile"),
    Rule("try_allowed_operator", _done("try_allowed_operator"), "already tried"),
    Rule("evaluate_profile_change", lambda s: not s["alternative_profile_installed"],
         "no alternate profile installed"),
    Rule("evaluate_profile_change", lambda s: not s["management_path_reachable"],
         "no reachable management path"),
    Rule("evaluate_profile_change", lambda s: s["active_profile"] != "profile_A",
         "alternate profile already enabled"),
    Rule("evaluate_profile_change", lambda s: s.get("profile_change_pending", False),
         "a profile plan is already awaiting approval"),
    Rule("evaluate_profile_change", lambda s: s.get("root_cause_layer") == "application",
         "diagnostics place the fault above the cellular layer"),
    Rule("evaluate_profile_change", lambda s: s.get("root_cause_layer") == "device",
         "diagnostics place the fault in device firmware"),
    Rule("retry_connection", lambda s: s["attempted_retries"] >= 3, "retry budget spent"),
    Rule("investigate_device", lambda s: not s["management_path_reachable"],
         "device cannot be reached for remote diagnostics"),
    Rule("investigate_device", _done("investigate_device"), "already collected"),
    Rule("investigate_data_path", _done("investigate_data_path"), "already collected"),
])

# Placeholder threshold: tune on dev fixtures before quoting any number.
LOW_CONFIDENCE = 0.0


def build_router(
    decider: DeciderClient,
    low_confidence: float = LOW_CONFIDENCE,
    actions: Mapping[str, Callable[[Any], Any]] | None = None,
) -> CapabilityAwareRouter:
    """`actions` overrides the tool per option (the twin passes its own); default: stubs."""
    options = [Option(n, d, (actions or {}).get(n, t)) for n, (d, t) in OPTION_SPECS.items()]
    return CapabilityAwareRouter(
        question=QUESTION,
        options=options,
        policy=POLICY,
        decider=decider,
        describe=describe,
        low_confidence=low_confidence,
        fallback=None,
    )
