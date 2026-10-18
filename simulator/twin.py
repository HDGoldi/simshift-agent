"""SIMShift digital twin: deterministic, seeded outcomes for one incident cohort.

SIMULATED. A simplified cohort-level model of cellular registration, data sessions, application
telemetry and a virtual eIM -> IPA -> eUICC profile path. It is not a 3GPP or GSMA SGP.32
implementation and talks to nothing real.

Separation of knowledge:
  * `observe()` returns ONLY observable fields (what the agent may see).
  * `self._cause` (the hidden root cause) drives effects but never appears in observe(),
    findings text, events, or outcome().
  * The same fixture + seed + action sequence always yields the same result.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from random import Random
from typing import Any

from simulator import scenarios

HEALTHY = 0.95  # registration and app-ACK rate that counts as restored

# simulated minutes each action costs (downtime accrues while the cohort is down)
COST_MIN = {
    "retry_connection": 15,
    "try_allowed_operator": 5,
    "investigate_device": 10,
    "investigate_data_path": 10,
    "evaluate_profile_change": 5,
    "escalate_or_wait": 30,
    "execute_profile_change": 20,
}

PROFILE_GUARDS: list[tuple[str, Callable[[dict[str, Any]], bool]]] = [
    ("eUICC does not support remote profile enable", lambda o: o["euicc_supports_remote_enable"]),
    ("no alternate profile installed", lambda o: o["alternative_profile_installed"]),
    ("no reachable management path", lambda o: o["management_path_reachable"]),
    ("owner has not permitted profile changes", lambda o: o["profile_change_permitted_by_owner"]),
]


class Twin:
    def __init__(self, fixture: dict[str, Any], seed: int = 7) -> None:
        self.id: str = fixture["id"]
        self.seed = seed
        self._cause: str = fixture["evaluator_only"]["true_cause"]
        self._rng = Random(f"{fixture['id']}:{seed}")
        self.obs: dict[str, Any] = copy.deepcopy(fixture["observable"])
        for k, v in {"findings": [], "steps_taken": [], "profile_change_pending": False, "escalated": False}.items():
            self.obs.setdefault(k, v)
        self.euicc = {
            "enabled": self.obs["active_profile"],
            "installed": [self.obs["active_profile"]] + (["profile_B"] if self.obs["alternative_profile_installed"] else []),
        }
        self.minutes = 0
        self.downtime_minutes = 0
        self.profile_changes = 0
        self.unnecessary_profile_changes = 0
        self.blocked_actions: list[dict[str, Any]] = []
        self.resolution: str | None = None
        self.events: list[dict[str, Any]] = []

    @classmethod
    def from_scenario(cls, name: str, seed: int = 7) -> Twin:
        return cls(scenarios.load(name), seed)

    # ------------------------------------------------------------------ views
    def observe(self) -> dict[str, Any]:
        return copy.deepcopy(self.obs)

    @property
    def restored(self) -> bool:
        return self.obs["attach_success_rate"] >= HEALTHY and self.obs["application_ack_rate"] >= HEALTHY

    @property
    def terminal(self) -> bool:
        return self.restored or self.obs["escalated"]

    def outcome(self) -> dict[str, Any]:
        return {
            "scenario": self.id,
            "seed": self.seed,
            "restored": self.restored,
            "registration_rate": round(self.obs["attach_success_rate"], 4),
            "application_ack_rate": round(self.obs["application_ack_rate"], 4),
            "resolution": self.resolution,
            "escalated": self.obs["escalated"],
            "steps": len(self.obs["steps_taken"]),
            "sim_minutes": self.minutes,
            "downtime_minutes": self.downtime_minutes,
            "profile_changes": self.profile_changes,
            "unnecessary_profile_changes": self.unnecessary_profile_changes,
            "blocked_actions": len(self.blocked_actions),
            "forbidden_executions": 0,  # guarded by construction; asserted in tests
            "enabled_profile": self.euicc["enabled"],
        }

    def clone(self) -> Twin:
        return copy.deepcopy(self)

    # ------------------------------------------------------------------ helpers
    def _tick(self, action: str) -> None:
        m = COST_MIN[action]
        self.minutes += m
        if not self.restored:
            self.downtime_minutes += m

    def _log(self, action: str, result: str, **extra: Any) -> str:
        self.events.append({"t_min": self.minutes, "action": action, "result": result} | extra)
        return result

    def _find(self, text: str) -> None:
        self.obs["findings"].append(text)

    def _restore(self, how: str, registration: bool = True, app: bool = True) -> None:
        if registration:
            self.obs["attach_success_rate"] = round(self._rng.uniform(0.965, 0.995), 4)
            self.obs["data_sessions_active_rate"] = round(self._rng.uniform(0.955, 0.99), 4)
            self.obs["last_heartbeat_minutes_ago"] = 1
        if app:
            self.obs["application_ack_rate"] = round(self._rng.uniform(0.96, 0.995), 4)
        if self.restored:
            self.resolution = how

    # ------------------------------------------------------------------ actions
    def tool(self, action: str) -> Callable[[Any], str]:
        """A router-compatible tool: ignores the passed state and acts on this twin."""

        def _run(_state: Any) -> str:
            return self.apply(action)

        _run.__name__ = TOOL_NAMES[action]
        return _run

    def apply(self, action: str) -> str:
        self.obs["steps_taken"].append(action)
        self._tick(action)
        return getattr(self, f"_a_{action}")()

    def _a_retry_connection(self) -> str:
        self.obs["attempted_retries"] += 1
        if self._cause == "transient_radio":
            self._restore("bounded_retry")
            return self._log("retry_connection", "SIM: retry succeeded; cohort re-registered")
        self._find(f"Retry {self.obs['attempted_retries']}: no change in attach or telemetry.")
        return self._log("retry_connection", "SIM: retry made no difference")

    def _a_try_allowed_operator(self) -> str:
        if self._cause == "primary_network_degraded" and self.obs["allowed_alternative_operator_available"]:
            self._restore("operator_reselection")
            return self._log("try_allowed_operator", "SIM: reselected permitted operator; cohort recovered")
        self._find("Operator reselection: no improvement.")
        return self._log("try_allowed_operator", "SIM: reselection did not help")

    def _a_investigate_device(self) -> str:
        if not self.obs["management_path_reachable"]:
            self._find("Device diagnostics: no response from devices.")
        elif self._cause == "firmware_regression":
            self._find("Device diagnostics: repeated modem resets on the newest firmware cohort. "
                       "Fault is in the device firmware, not the network or profile.")
            self.obs["root_cause_layer"] = "device"
        else:
            self._find("Device diagnostics: modem and firmware healthy, no resets.")
        return self._log("investigate_device", "SIM: device diagnostics collected", finding=self.obs["findings"][-1])

    def _a_investigate_data_path(self) -> str:
        if self._cause == "cloud_ingestion_regression":
            self._find(
                "Data-path diagnostics: cellular data sessions healthy; the cloud ingestion endpoint "
                "rejects messages since a deployment this morning. Fault is above the cellular layer."
            )
            self.obs["root_cause_layer"] = "application"
        elif self.obs["attach_success_rate"] < 0.5:
            self._find("Data-path diagnostics: no data sessions because devices are not registered on any network.")
            self.obs["root_cause_layer"] = "cellular"
        else:
            self._find("Data-path diagnostics: no fault found on APN, sessions or ingestion.")
        return self._log("investigate_data_path", "SIM: data-path diagnostics collected", finding=self.obs["findings"][-1])

    def _a_evaluate_profile_change(self) -> str:
        blocked = self.guard_profile_change()
        if blocked:
            self.blocked_actions.append({"action": "evaluate_profile_change", "reasons": blocked})
            return self._log("evaluate_profile_change", "SIM: BLOCKED - " + "; ".join(blocked))
        self.obs["profile_change_pending"] = True
        return self._log(
            "evaluate_profile_change",
            f"SIM: plan ready - enable {self.euicc['installed'][-1]} via virtual eIM; all checks pass; awaiting human approval",
        )

    def _a_escalate_or_wait(self) -> str:
        self.obs["escalated"] = True
        if self.obs.get("root_cause_layer") == "application":
            self._restore("application_team_fix", registration=False, app=True)
            return self._log("escalate_or_wait", "SIM: handed to application team; ingestion rollback restored telemetry")
        if self.obs.get("root_cause_layer") == "device":
            self._restore("firmware_rollback")
            return self._log("escalate_or_wait", "SIM: handed to device team; firmware rollback restored the cohort")
        return self._log("escalate_or_wait", "SIM: escalated to field operations; no remote change attempted")

    # ------------------------------------------------------------------ guarded profile path
    def guard_profile_change(self) -> list[str]:
        return [reason for reason, ok in PROFILE_GUARDS if not ok(self.obs)]

    def execute_profile_change(self, approved: bool) -> dict[str, Any]:
        """eIM -> IPA -> eUICC enable. Runs only if every guard passes AND a human approved."""
        reasons = self.guard_profile_change()
        if not self.obs["profile_change_pending"]:
            reasons.append("no evaluated plan")
        if not approved:
            reasons.append("not approved")
        if reasons:
            self.blocked_actions.append({"action": "execute_profile_change", "reasons": reasons})
            self._log("execute_profile_change", "SIM: BLOCKED - " + "; ".join(reasons))
            return {"executed": False, "blocked_reasons": reasons}

        self._tick("execute_profile_change")
        target = self.euicc["installed"][-1]
        timeline = [
            "eIM: enable command queued",
            "IPA: command received over management path",
            f"eUICC: {self.euicc['enabled']} disabled, {target} enabled",
        ]
        self.euicc["enabled"] = target
        self.obs["active_profile"] = target
        self.obs["profile_change_pending"] = False
        self.profile_changes += 1
        if self._cause == "active_profile_not_viable_in_region":
            self._restore("profile_switch")
            timeline += ["network: registration restored", "cloud: telemetry acknowledged"]
        else:
            self.unnecessary_profile_changes += 1
            timeline += ["network: re-registered on new profile", "cloud: telemetry still failing"]
        self._log("execute_profile_change", "SIM: profile enabled", timeline=timeline)
        return {"executed": True, "timeline": timeline, "restored": self.restored}


TOOL_NAMES = {
    "retry_connection": "simulate_retry_with_backoff",
    "try_allowed_operator": "simulate_operator_reselection",
    "investigate_device": "query_firmware_modem_diagnostics",
    "investigate_data_path": "query_apn_session_app_diagnostics",
    "evaluate_profile_change": "prepare_guarded_profile_transition",
    "escalate_or_wait": "defer_or_escalate",
}


def replay(name: str, actions: list[str], approve: bool = True, seed: int = 7) -> dict[str, Any]:
    """Counterfactual: run a fixed action sequence on a fresh twin. Profile plans are
    executed with `approve`. Guards still apply; nothing bypasses them."""
    t = Twin.from_scenario(name, seed)
    for a in actions:
        if t.terminal:
            break
        t.apply(a)
        if a == "evaluate_profile_change" and t.obs["profile_change_pending"]:
            t.execute_profile_change(approve)
    return {"actions": actions, "outcome": t.outcome(), "events": t.events}
