"""SIMShift Decider spike: prove that a real Strands Decider 2B choice picks the tool that runs.

Flow per scenario:
    observable state -> deterministic policy filter (with reasons) -> Decider typed choice
    -> re-check -> the chosen option's tool executes -> trace line (JSONL).

Everything here is SIMULATED. Tools are stubs; no network, carrier or eUICC is touched.

Run (needs a local server):
    strands-decider serve StrandsAgents/strands-decider-2B-qwen3.5-v1-2610 --device cpu --port 8099
    python spike/decider_spike.py
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

DECIDER_URL = os.environ.get("STRANDS_DECIDER_URL", "http://127.0.0.1:8099")
TRACE_PATH = Path(__file__).parent / "logs" / "trace.jsonl"

# --------------------------------------------------------------------------- the question

QUESTION = (
    "Given the current cellular connectivity symptoms, existing diagnostic evidence, and "
    "admissible tools, which next tool is most useful for safely advancing service restoration? "
    "Do not assume that an unverified recovery path works."
)

# option -> what it means (sent to Decider as `criteria`)
CRITERIA: dict[str, str] = {
    "retry_connection": "bounded backoff and retry on the current subscription; fits brief, improving disruptions",
    "try_allowed_operator": "attach to another network that the active profile already permits; no profile change",
    "investigate_device": "read-only modem and firmware diagnostics; fits device resets or firmware cohorts",
    "investigate_data_path": "read-only APN, data session and application ingestion diagnostics; fits devices that are registered but whose data is not arriving",
    "evaluate_profile_change": "check feasibility of enabling a different installed eSIM profile; does not execute it",
    "escalate_or_wait": "hold and hand to a human; fits cases where no remote action can reach the devices",
}


# --------------------------------------------------------------------------- tools (stubs)

def simulate_retry_with_backoff(s: Mapping[str, Any]) -> str:
    return "SIM: bounded retry scheduled (3 attempts, exponential backoff)"


def simulate_operator_reselection(s: Mapping[str, Any]) -> str:
    return "SIM: reselection to permitted alternate operator requested"


def query_firmware_modem_diagnostics(s: Mapping[str, Any]) -> str:
    return "SIM: modem/firmware diagnostics collected"


def query_apn_session_app_diagnostics(s: Mapping[str, Any]) -> str:
    return "SIM: data-path diagnostics collected"


def prepare_guarded_profile_transition(s: Mapping[str, Any]) -> str:
    return "SIM: guarded profile-transition workflow OPENED (needs capability, reachability, permission, approval)"


def defer_or_escalate(s: Mapping[str, Any]) -> str:
    return "SIM: incident escalated to human operator"


TOOLS: dict[str, Callable[[Mapping[str, Any]], str]] = {
    "retry_connection": simulate_retry_with_backoff,
    "try_allowed_operator": simulate_operator_reselection,
    "investigate_device": query_firmware_modem_diagnostics,
    "investigate_data_path": query_apn_session_app_diagnostics,
    "evaluate_profile_change": prepare_guarded_profile_transition,
    "escalate_or_wait": defer_or_escalate,
}


# --------------------------------------------------------------------------- policy

def allowed_actions(s: Mapping[str, Any]) -> tuple[list[str], dict[str, str]]:
    """Deterministic filter. Returns (allowed options, {removed option: reason})."""
    removed: dict[str, str] = {}
    if not s["allowed_alternative_operator_available"]:
        removed["try_allowed_operator"] = "no permitted alternate operator on the active profile"
    if not s["alternative_profile_installed"]:
        removed["evaluate_profile_change"] = "no alternate profile installed"
    elif not s["management_path_reachable"]:
        removed["evaluate_profile_change"] = "no reachable management path"
    if s["attempted_retries"] >= 3:
        removed["retry_connection"] = "retry budget spent"
    if not s["management_path_reachable"]:
        # device-side diagnostics need the device; cloud-side data-path checks and retries do not
        removed.setdefault("investigate_device", "device cannot be reached for remote diagnostics")
    allowed = [o for o in CRITERIA if o not in removed]
    return allowed, removed


# --------------------------------------------------------------------------- decider

class DeciderLike(Protocol):
    def choose(self, state: Mapping[str, Any], options: list[str]) -> dict[str, Any]: ...


def describe(s: Mapping[str, Any]) -> str:
    """Plain-language observations. The model reads text; raw flags read worse (spike finding)."""
    pct = lambda x: f"{x * 100:.1f}%"  # noqa: E731
    lines = [
        f"Incident: {s['incident']}. {s['affected_devices']} devices affected.",
        f"Network registration (attach) success: {pct(s['attach_success_rate'])}.",
        f"Active data sessions: {pct(s['data_sessions_active_rate'])}.",
        f"Application messages acknowledged by the cloud: {pct(s['application_ack_rate'])}.",
        f"Last heartbeat: {s['last_heartbeat_minutes_ago']} minutes ago.",
        "Management path to the devices: " + ("reachable." if s["management_path_reachable"] else "NOT reachable."),
        "Alternate eSIM profile installed: " + ("yes." if s["alternative_profile_installed"] else "no."),
        f"Retries already attempted: {s['attempted_retries']}.",
        "Recent firmware change: " + ("yes." if s["recent_firmware_change"] else "no."),
    ]
    return "\n".join(lines)


class HttpDecider:
    """Thin client for `POST /v1/systemone` (strands-decider 0.1.0)."""

    def __init__(self, url: str = DECIDER_URL, timeout: float = 300.0, prose: bool = True) -> None:
        self.url, self.timeout, self.prose = url.rstrip("/"), timeout, prose

    def choose(self, state: Mapping[str, Any], options: list[str]) -> dict[str, Any]:
        body = {
            "state": describe(state) if self.prose else dict(state),
            "questions": {
                "next_tool": {
                    "type": "choice",
                    "instructions": QUESTION,
                    "criteria": {o: CRITERIA[o] for o in options},
                },
                "evidence_sufficient": {
                    "type": "noul",
                    "instructions": "Is the current evidence sufficient to choose a next step confidently?",
                },
            },
        }
        req = urllib.request.Request(
            f"{self.url}/v1/systemone",
            data=json.dumps(body).encode(),
            headers={"content-type": "application/json"},
        )
        t0 = time.perf_counter()
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            payload = json.loads(resp.read())
        payload["client_wall_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        payload["request"] = body
        return payload


# --------------------------------------------------------------------------- router

LOW_CONFIDENCE = 0.5  # placeholder; tune on dev fixtures before any claim


@dataclass
class StepResult:
    scenario: str
    allowed: list[str]
    removed: dict[str, str]
    choice: str
    probabilities: dict[str, float]
    confidence: float
    evidence_sufficient: float | None
    tool: str
    tool_output: str
    low_confidence: bool
    decider_latency_ms: float | None
    raw: dict[str, Any] = field(repr=False, default_factory=dict)


def route(scenario: str, state: Mapping[str, Any], decider: DeciderLike) -> StepResult:
    allowed, removed = allowed_actions(state)
    if not allowed:
        allowed, removed = ["escalate_or_wait"], removed
    payload = decider.choose(state, allowed)
    ans = payload["answers"]["next_tool"]
    choice = ans["choice"]
    if choice not in allowed:  # re-check: never run something the policy removed
        raise RuntimeError(f"decider returned non-admissible option {choice!r}")
    tool = TOOLS[choice]
    out = tool(state)
    ev = payload["answers"].get("evidence_sufficient", {}).get("noul")
    return StepResult(
        scenario=scenario,
        allowed=allowed,
        removed=removed,
        choice=choice,
        probabilities=ans["probabilities"],
        confidence=ans["confidence"],
        evidence_sufficient=ev,
        tool=tool.__name__,
        tool_output=out,
        low_confidence=ans["confidence"] < LOW_CONFIDENCE,
        decider_latency_ms=payload.get("latency_ms"),
        raw=payload,
    )


# --------------------------------------------------------------------------- scenarios (synthetic)

BASE = {
    "affected_devices": 0,
    "attach_success_rate": 1.0,
    "data_sessions_active_rate": 1.0,
    "application_ack_rate": 1.0,
    "last_heartbeat_minutes_ago": 1,
    "active_profile": "profile_A",
    "allowed_alternative_operator_available": False,
    "alternative_profile_installed": False,
    "management_path_reachable": True,
    "recent_firmware_change": False,
    "attempted_retries": 0,
}

SCENARIOS: dict[str, dict[str, Any]] = {
    "BR_PROFILE": BASE | {
        "incident": "Persistent cellular attach failures in Brazil cohort",
        "affected_devices": 3200,
        "attach_success_rate": 0.04,
        "data_sessions_active_rate": 0.03,
        "application_ack_rate": 0.03,
        "alternative_profile_installed": True,
        "attempted_retries": 3,
    },
    "OFFLINE": BASE | {
        "incident": "Remote cohort silent; no heartbeat",
        "affected_devices": 1250,
        "attach_success_rate": 0.0,
        "data_sessions_active_rate": 0.0,
        "application_ack_rate": 0.0,
        "last_heartbeat_minutes_ago": 720,
        "alternative_profile_installed": True,
        "management_path_reachable": False,
        "attempted_retries": 2,
    },
    "JP_INGEST": BASE | {
        "incident": "Japan cohort telemetry missing",
        "affected_devices": 11600,
        "attach_success_rate": 0.997,
        "data_sessions_active_rate": 0.99,
        "application_ack_rate": 0.02,
        "alternative_profile_installed": True,
        "attempted_retries": 1,
    },
}


def main() -> None:
    decider = HttpDecider()
    TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with TRACE_PATH.open("a") as f:
        for name, state in SCENARIOS.items():
            r = route(name, state, decider)
            line = {k: v for k, v in r.__dict__.items() if k != "raw"}
            line["ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            line["model"] = r.raw.get("model")
            line["usage"] = r.raw.get("usage")
            line["client_wall_ms"] = r.raw.get("client_wall_ms")
            f.write(json.dumps(line) + "\n")
            probs = ", ".join(f"{k}={v:.3f}" for k, v in sorted(r.probabilities.items(), key=lambda kv: -kv[1]))
            print(f"\n[{name}] removed={list(r.removed)}")
            print(f"  -> {r.choice} (conf {r.confidence:.3f}; evidence_sufficient {r.evidence_sufficient})")
            print(f"     probs: {probs}")
            print(f"     tool: {r.tool} | {r.tool_output}")
            print(f"     decider latency {r.decider_latency_ms} ms, wall {r.raw.get('client_wall_ms')} ms, low_conf={r.low_confidence}")


if __name__ == "__main__":
    main()
