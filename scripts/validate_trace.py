# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

"""Validate captured BR, OFFLINE, and forced-policy evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from simshift.tracing.events import TraceEvent, validate_event_sequence


def load_trace(path: Path) -> tuple[TraceEvent, ...]:
    events = tuple(
        TraceEvent.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    validate_event_sequence(events)
    return events


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("br", type=Path)
    parser.add_argument("offline", type=Path)
    parser.add_argument("policy", type=Path)
    args = parser.parse_args()

    br = load_trace(args.br)
    br_types = [event.event_type for event in br]
    required = {
        "decider_health_checked",
        "decider_request",
        "decider_response",
        "tool_dispatch_finished",
        "proposal_prepared",
        "approval_consumed",
        "transition_changed",
        "registration_check",
        "telemetry_check",
        "run_completed",
    }
    if not required <= set(br_types):
        raise ValueError(f"BR trace is missing events: {sorted(required - set(br_types))}")
    br_terminal = br[-1].payload
    if br[-1].event_type != "run_completed" or br_terminal["final_status"] != "RESTORED":
        raise ValueError("BR trace does not end RESTORED")
    if not any(
        event.event_type == "transition_changed" and event.payload["new_state"] == "SUCCEEDED"
        for event in br
    ):
        raise ValueError("BR trace has no SUCCEEDED transition")

    offline = load_trace(args.offline)
    if offline[-1].event_type != "run_escalated":
        raise ValueError("OFFLINE trace does not end in escalation")
    if any(event.event_type in {"approval_consumed", "transition_changed"} for event in offline):
        raise ValueError("OFFLINE trace contains a transition lifecycle")

    policy = json.loads(args.policy.read_text(encoding="utf-8"))
    if not (
        policy.get("status") == "BLOCKED"
        and "MANAGEMENT_UNREACHABLE" in policy.get("reasons", [])
        and policy.get("transition_id") is None
        and policy.get("final_profile") == "profile_A"
        and policy.get("profile_unchanged") is True
    ):
        raise ValueError("OFFLINE forced-policy evidence is not safely blocked")
    print("validated real Decider BR/OFFLINE evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
