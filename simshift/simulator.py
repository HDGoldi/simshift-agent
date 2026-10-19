"""Deterministic cohort-level digital twin of a cellular IoT fleet, plus a virtual eIM/IPA/eUICC.

Everything here is SYNTHETIC. No carrier, eUICC, SM-DP+ or SGP.32 operation is performed.
The eSIM part is a simplified profile-enable state machine, not a certified GSMA flow.

Terminology kept distinct on purpose:
  - operator reselection: attach to another operator allowed by the *active* profile
  - profile switch: enable a different *installed* profile on the eUICC (needs a management path)
"""
from __future__ import annotations

import copy
import hashlib

RESTORED_THRESHOLD = 0.95

# Hidden truth lives under "hidden" and in "networks"/"ingestion_healthy"; observe() never returns them.
SCENARIOS: dict[str, dict] = {
    "BR_PROFILE": {
        "title": "Brazil: active profile cannot register; alternate installed profile",
        "incident": "Persistent cellular attach failures",
        "country": "BR",
        "devices": 3200,
        "serving_operator": "BR-NET-1",
        "active_profile": "profile_A",
        "profiles": {"profile_A": {"operators": ["BR-NET-1"]}, "profile_B": {"operators": ["BR-NET-2"]}},
        "operators_in_coverage": ["BR-NET-1", "BR-NET-2"],
        "networks": {"BR-NET-1": "down", "BR-NET-2": "up"},
        "ingestion_healthy": True,
        # Depot-mounted trackers keep a non-cellular IP path (gateway Wi-Fi) to the eIM. Without it,
        # a profile change on a device that cannot register would be unreachable (see OFFLINE).
        "management": {"up": True, "via_cellular": False, "path": "depot gateway Wi-Fi (non-cellular IP)"},
        "euicc": {"supports_profile_enable": True, "rollback_supported": True},
        "owner_allows_profile_switch": True,
        "recent_firmware_change": False,
        "attempted_retries": 3,
        "hidden": {"cause": "primary operator BR-NET-1 outage; profile_A has no other operator",
                   "best_actions": ["evaluate_profile_change"]},
    },
    "OFFLINE": {
        "title": "Remote devices: no heartbeat, no management path",
        "incident": "Devices silent; no heartbeat",
        "country": "CL",
        "devices": 1250,
        "serving_operator": "CL-NET-1",
        "active_profile": "profile_A",
        "profiles": {"profile_A": {"operators": ["CL-NET-1"]}, "profile_B": {"operators": ["CL-NET-2"]}},
        "operators_in_coverage": [],  # unknown: devices report nothing
        "networks": {"CL-NET-1": "up", "CL-NET-2": "up"},
        "ingestion_healthy": True,
        "management": {"up": False, "via_cellular": False, "path": None},
        "euicc": {"supports_profile_enable": True, "rollback_supported": True},
        "owner_allows_profile_switch": True,
        "recent_firmware_change": False,
        "attempted_retries": 2,
        "device_powered": False,
        "hidden": {"cause": "devices lost power at remote site (field issue, not network)",
                   "best_actions": ["escalate_or_wait", "investigate_data_path"]},
    },
    "JP_INGEST": {
        "title": "Japan: cellular healthy, application ACKs failing",
        "incident": "Telemetry not arriving",
        "country": "JP",
        "devices": 11600,
        "serving_operator": "JP-NET-1",
        "active_profile": "profile_A",
        "profiles": {"profile_A": {"operators": ["JP-NET-1"]}, "profile_B": {"operators": ["JP-NET-2"]}},
        "operators_in_coverage": ["JP-NET-1", "JP-NET-2"],
        "networks": {"JP-NET-1": "up", "JP-NET-2": "up"},
        "ingestion_healthy": False,
        "management": {"up": True, "via_cellular": True, "path": "cellular IP via active profile"},
        "euicc": {"supports_profile_enable": True, "rollback_supported": True},
        "owner_allows_profile_switch": True,
        "recent_firmware_change": False,
        "attempted_retries": 0,
        "hidden": {"cause": "cloud ingestion deploy ingest-v2.14 rejects payloads (HTTP 5xx)",
                   "best_actions": ["investigate_data_path"]},
    },
    "DE_OPERATOR": {
        "title": "Germany: primary network degraded; allowed alternative operator on same profile",
        "incident": "Attach failures on primary network",
        "country": "DE",
        "devices": 8400,
        "serving_operator": "DE-NET-1",
        "active_profile": "profile_A",
        "profiles": {"profile_A": {"operators": ["DE-NET-1", "DE-NET-2"]}, "profile_B": {"operators": ["DE-NET-3"]}},
        "operators_in_coverage": ["DE-NET-1", "DE-NET-2", "DE-NET-3"],
        "networks": {"DE-NET-1": "down", "DE-NET-2": "up", "DE-NET-3": "up"},
        "ingestion_healthy": True,
        "management": {"up": True, "via_cellular": True, "path": "cellular IP via active profile"},
        "euicc": {"supports_profile_enable": True, "rollback_supported": True},
        "owner_allows_profile_switch": True,
        "recent_firmware_change": False,
        "attempted_retries": 1,
        "hidden": {"cause": "DE-NET-1 regional outage; DE-NET-2 allowed on active profile",
                   "best_actions": ["try_allowed_operator"]},
    },
    "FW_LOOP": {
        "title": "US: devices keep dropping off after a firmware rollout",
        "incident": "Devices dropping off the network repeatedly",
        "country": "US",
        "devices": 5400,
        "serving_operator": "US-NET-1",
        "active_profile": "profile_A",
        "profiles": {"profile_A": {"operators": ["US-NET-1"]}, "profile_B": {"operators": ["US-NET-2"]}},
        "operators_in_coverage": ["US-NET-1", "US-NET-2"],
        "networks": {"US-NET-1": "up", "US-NET-2": "up"},
        "ingestion_healthy": True,
        "management": {"up": True, "via_cellular": True, "path": "cellular IP via active profile"},
        "euicc": {"supports_profile_enable": True, "rollback_supported": True},
        "owner_allows_profile_switch": True,
        "recent_firmware_change": True,
        "attempted_retries": 2,
        "attach_trend": "flapping",
        "firmware_fault": True,
        "hidden": {"cause": "firmware 4.2.0 modem reset loop (device-side regression)",
                   "best_actions": ["investigate_device", "escalate_or_wait"]},
    },
    "TRANSIENT": {
        "title": "France: short burst of attach failures after a cell site restart",
        "incident": "Short burst of attach failures",
        "country": "FR",
        "devices": 2100,
        "serving_operator": "FR-NET-1",
        "active_profile": "profile_A",
        "profiles": {"profile_A": {"operators": ["FR-NET-1"]}, "profile_B": {"operators": ["FR-NET-2"]}},
        "operators_in_coverage": ["FR-NET-1", "FR-NET-2"],
        "networks": {"FR-NET-1": "up", "FR-NET-2": "up"},
        "ingestion_healthy": True,
        "management": {"up": True, "via_cellular": True, "path": "cellular IP via active profile"},
        "euicc": {"supports_profile_enable": True, "rollback_supported": True},
        "owner_allows_profile_switch": True,
        "recent_firmware_change": False,
        "attempted_retries": 0,
        "attach_trend": "improving",
        "transient_congestion": True,
        "hidden": {"cause": "radio congestion after a cell site restart; clears on re-attach",
                   "best_actions": ["retry_connection"]},
    },
}

# Simulated minutes each twin action takes while the incident is open (the agent only acts while it is open).
COST_MIN = {"retry": 5, "operator_reselection": 10, "diagnostics_device": 15, "diagnostics_data_path": 10,
            "eim_enable_profile": 30, "eim_rollback": 20, "escalated": 60}


class FleetTwin:
    """One incident cohort. All transitions are pure functions of state, so clones replay identically."""

    def __init__(self, scenario_id: str):
        self.scenario_id = scenario_id
        self.s = copy.deepcopy(SCENARIOS[scenario_id])
        self.diagnostics: dict[str, dict] = {}
        self.events: list[dict] = []
        self.commands: dict[str, dict] = {}  # idempotency key -> result
        self.profile_changes = 0  # executed profile enables (rollbacks not subtracted)

    def clone(self) -> "FleetTwin":
        return copy.deepcopy(self)

    # ---- observation -------------------------------------------------------------------------
    def _registered(self) -> bool:
        s = self.s
        op = s["serving_operator"]
        return (s.get("device_powered", True)
                and op in s["profiles"][s["active_profile"]]["operators"]
                and s["networks"].get(op) == "up")

    def management_reachable(self) -> bool:
        """A cellular management path only works while the active profile is registered."""
        m = self.s["management"]
        return m["up"] and (not m["via_cellular"] or self._registered())

    def rates(self) -> dict:
        if not self.s.get("device_powered", True):
            return {"attach_success_rate": 0.0, "data_session_rate": 0.0, "app_ack_rate": 0.0, "heartbeat_rate": 0.0}
        reg = self._registered()
        if reg and (self.s.get("firmware_fault") or self.s.get("transient_congestion")):
            a = 0.41 if self.s.get("firmware_fault") else 0.62  # modem reset loop / congestion: partial service
            return {"attach_success_rate": a, "data_session_rate": a - 0.03, "app_ack_rate": a - 0.04,
                    "heartbeat_rate": a + 0.01}
        attach = 0.997 if reg else 0.04
        ack = 0.995 if (reg and self.s["ingestion_healthy"]) else 0.02 if reg else 0.0
        return {"attach_success_rate": attach, "data_session_rate": 0.99 if reg else 0.03,
                "app_ack_rate": ack, "heartbeat_rate": 0.99 if reg else 0.04}

    def service_restored(self) -> bool:
        r = self.rates()
        return r["attach_success_rate"] >= RESTORED_THRESHOLD and r["app_ack_rate"] >= RESTORED_THRESHOLD

    def observe(self) -> dict:
        """Observable state only. Never includes hidden cause, network health, or ingestion health."""
        s = self.s
        active_ops = s["profiles"][s["active_profile"]]["operators"]
        return {
            "incident": s["incident"],
            "country": s["country"],
            "affected_devices": s["devices"],
            **self.rates(),
            "serving_operator": s["serving_operator"],
            "active_profile": s["active_profile"],
            "other_operator_allowed_on_active_profile": any(
                o != s["serving_operator"] and o in s["operators_in_coverage"] for o in active_ops),
            "alternative_profile_installed": len(s["profiles"]) > 1,
            "management_path_reachable": self.management_reachable(),
            "recent_firmware_change": s["recent_firmware_change"],
            **({"attach_trend": s["attach_trend"]} if "attach_trend" in s else {}),
            "attempted_retries": s["attempted_retries"],
            "diagnostics": copy.deepcopy(self.diagnostics),
        }

    def _log(self, kind: str, **data) -> dict:
        ev = {"seq": len(self.events) + 1, "kind": kind, **data}
        self.events.append(ev)
        return ev

    # ---- network-side actions ----------------------------------------------------------------
    def retry_with_backoff(self) -> dict:
        self.s["attempted_retries"] += 1
        if self.s.get("transient_congestion") and self._registered():
            self.s["transient_congestion"] = False  # congestion clears on a fresh attach; a reset loop does not
        return self._log("retry", restored=self.service_restored(), rates=self.rates())

    def operator_reselection(self) -> dict:
        s = self.s
        candidates = [o for o in s["profiles"][s["active_profile"]]["operators"]
                      if o != s["serving_operator"] and o in s["operators_in_coverage"]]
        if not candidates:
            return self._log("operator_reselection", ok=False, reason="no allowed alternative operator in coverage")
        prev, s["serving_operator"] = s["serving_operator"], candidates[0]
        return self._log("operator_reselection", ok=True, from_operator=prev, to_operator=candidates[0],
                         restored=self.service_restored(), rates=self.rates())

    # ---- read-only diagnostics ---------------------------------------------------------------
    def firmware_modem_diagnostics(self) -> dict:
        if not self.management_reachable():
            d = {"available": False, "reason": "device unreachable; no modem logs retrievable"}
        else:
            reg = self._registered()
            if self.s.get("firmware_fault"):
                d = {"available": True, "firmware_uniform": True, "modem_resets_per_day": 14.2, "reject_cause": None,
                     "summary": "modem reset loop on the firmware rolled out before onset; registration accepted between resets"}
                self.diagnostics["device"] = d
                return self._log("diagnostics_device", result=d)
            d = {"available": True, "firmware_uniform": True, "modem_resets_per_day": 0.1,
                 "reject_cause": None if reg else "#17 network failure from serving operator",
                 "summary": "modem healthy" if reg else
                 f"modem healthy; registration rejected by {self.s['serving_operator']}"}
        self.diagnostics["device"] = d
        return self._log("diagnostics_device", result=d)

    def data_path_diagnostics(self) -> dict:
        s = self.s
        if not s.get("device_powered", True):
            d = {"network_side_attach_attempts_last_6h": 0,
                 "summary": "no attach attempts seen by any network; last known cells normal (power/field issue suspected)"}
        elif self._registered() and not s["ingestion_healthy"]:
            d = {"pdn_sessions": "established", "apn": "ok", "ingest_http_5xx_rate": 0.98,
                 "summary": "cellular + APN healthy; ingestion endpoint rejecting payloads since deploy ingest-v2.14"}
        elif not self._registered():
            d = {"pdn_sessions": "none", "summary": f"no data sessions; attach failing on {s['serving_operator']}"}
        elif s.get("firmware_fault"):
            d = {"pdn_sessions": "flapping", "apn": "ok", "summary": "sessions drop and re-establish repeatedly; APN and ingestion healthy"}
        elif s.get("transient_congestion"):
            d = {"pdn_sessions": "partly established", "apn": "ok",
                 "summary": f"intermittent RRC setup failures on {s['serving_operator']} cells; failure rate falling"}
        else:
            d = {"pdn_sessions": "established", "apn": "ok", "summary": "data path healthy"}
        self.diagnostics["data_path"] = d
        return self._log("diagnostics_data_path", result=d)

    # ---- virtual eIM / IPA / eUICC -----------------------------------------------------------
    def get_profiles(self) -> dict:
        s = self.s
        return {"active": s["active_profile"],
                "installed": {p: {"operators": v["operators"], "enabled": p == s["active_profile"]}
                              for p, v in s["profiles"].items()}}

    def enable_profile(self, target: str, idempotency_key: str, *, approved: bool) -> dict:
        """Simulator-only. Independent of the policy gate, the virtual eIM refuses unapproved or undeliverable commands."""
        if not approved:  # not cached: a later approved attempt with the same key must really execute
            return self._log("eim_enable_profile", ok=False, reason="no operator approval; command not sent")
        if idempotency_key in self.commands:
            return self.commands[idempotency_key]
        s = self.s
        if not self.management_reachable():
            res = self._log("eim_enable_profile", ok=False, reason="IPA unreachable; command not delivered")
        else:
            prev = s["active_profile"]
            s["active_profile"] = target
            ops = [o for o in s["profiles"][target]["operators"] if o in s["operators_in_coverage"]]
            if ops:
                s["serving_operator"] = ops[0]
            self.profile_changes += 1
            res = self._log("eim_enable_profile", ok=True, from_profile=prev, to_profile=target,
                            ipa_ack=True, serving_operator=s["serving_operator"],
                            restored=self.service_restored(), rates=self.rates())
        self.commands[idempotency_key] = res
        return res

    def escalate(self) -> dict:
        return self._log("escalated", evidence=copy.deepcopy(self.diagnostics))

    def simulated_minutes(self) -> int:
        return sum(COST_MIN.get(e["kind"], 0) for e in self.events)

    def rollback_profile(self, previous: str, previous_operator: str) -> dict:
        if not self.s["euicc"]["rollback_supported"]:
            return self._log("eim_rollback", ok=False, reason="rollback not supported")
        if not self.management_reachable():  # same path rule as enable: a cellular path needs a registered profile
            return self._log("eim_rollback", ok=False, reason="IPA unreachable; rollback not delivered")
        self.commands.clear()  # earlier enable results are superseded; a new attempt must really execute
        self.s["active_profile"], self.s["serving_operator"] = previous, previous_operator
        return self._log("eim_rollback", ok=True, to_profile=previous, rates=self.rates())


def idempotency_key(scenario_id: str, from_profile: str, to_profile: str) -> str:
    return hashlib.sha256(f"{scenario_id}:{from_profile}->{to_profile}".encode()).hexdigest()[:16]
