"""Load synthetic scenarios and render the OBSERVABLE part as text for the decision model.

`evaluator_only` (hidden true cause, acceptable answers) never leaves this module through
`observe()` / `describe()`; only the evaluation harness reads it via `load()`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

SCENARIO_DIR = Path(__file__).parent / "scenarios"


def load(name: str) -> dict[str, Any]:
    """Full fixture, including evaluator_only. For the evaluation harness."""
    return json.loads((SCENARIO_DIR / f"{name}.json").read_text())


def names() -> list[str]:
    return sorted(p.stem for p in SCENARIO_DIR.glob("*.json"))


def observe(name: str) -> dict[str, Any]:
    """What the agent may see: observable fields only."""
    return dict(load(name)["observable"])


def describe(s: Mapping[str, Any]) -> str:
    """Plain-language observations. In the spike, prose beat raw fields (fixed the Japan case)."""

    def pct(x: float) -> str:
        return f"{x * 100:.1f}%"

    lines = [
        f"Incident: {s['incident']}. {s['affected_devices']} devices affected.",
        f"Network registration (attach) success: {pct(s['attach_success_rate'])}.",
        f"Active data sessions: {pct(s['data_sessions_active_rate'])}.",
        f"Application messages acknowledged by the cloud: {pct(s['application_ack_rate'])}.",
        f"Last heartbeat: {s['last_heartbeat_minutes_ago']} minutes ago.",
        "Management path to the devices: " + ("reachable." if s["management_path_reachable"] else "NOT reachable."),
        f"Active eSIM profile: {s['active_profile']}.",
        "Alternate eSIM profile installed: " + ("yes." if s["alternative_profile_installed"] else "no."),
        "Permitted alternate operator on active profile: "
        + ("yes." if s["allowed_alternative_operator_available"] else "no."),
        f"Retries already attempted: {s['attempted_retries']}.",
        "Recent firmware change: " + ("yes." if s["recent_firmware_change"] else "no."),
    ]
    if "attach_trend" in s:
        lines.append(f"Attach success trend over the last 15 minutes: {s['attach_trend']}.")
    if "modem_resets_per_hour" in s:
        lines.append(f"Modem resets per device per hour: {s['modem_resets_per_hour']}.")
    if s.get("steps_taken"):
        lines.append("Steps already taken: " + ", ".join(s["steps_taken"]) + ".")
    for f in s.get("findings", []):
        lines.append(f"Finding: {f}")
    return "\n".join(lines)
