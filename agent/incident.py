"""One incident, end to end: twin -> router (policy + Decider) -> tool -> approval gate -> twin.

Shared by the CLI (router mode), the Strands agent's `advance_recovery` tool and the web UI.

Approval modes:
  * `approve=callable`  decides immediately inside step() (CLI demo flag, agent).
  * `approve=None`      DEFERS: step() stops with approval "pending"; a human calls resolve_approval().
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from decider.recovery_decisions import OPTION_SPECS, build_router
from patterns.capability_aware_router import CapabilityAwareRouter, DeciderClient
from simulator.twin import Twin

# approve(twin, plan_text) -> bool. A HUMAN decision; the demo passes a flag.
Approver = Callable[[Twin, str], bool]


def deny_all(_twin: Twin, _plan: str) -> bool:
    return False


class Incident:
    def __init__(self, scenario: str | dict[str, Any], decider: DeciderClient, approve: Approver | None = deny_all,
                 seed: int = 7, max_steps: int = 5) -> None:
        """`scenario` is a fixture name, or a fixture dict (evaluation datasets)."""
        if isinstance(scenario, dict):
            self.scenario = scenario["id"]
            self.twin = Twin(scenario, seed)
        else:
            self.scenario = scenario
            self.twin = Twin.from_scenario(scenario, seed)
        self.approve = approve
        self.max_steps = max_steps
        self.steps: list[dict[str, Any]] = []
        self.router: CapabilityAwareRouter = build_router(
            decider, actions={n: self.twin.tool(n) for n in OPTION_SPECS}
        )

    @property
    def awaiting_approval(self) -> bool:
        return bool(self.steps) and self.steps[-1].get("approval") == "pending"

    @property
    def done(self) -> bool:
        if self.awaiting_approval:
            return False
        return self.twin.terminal or len(self.steps) >= self.max_steps or (
            bool(self.steps) and self.steps[-1]["executed"] is None
        )

    def _after(self) -> dict[str, Any]:
        return {
            "registration_rate": self.twin.obs["attach_success_rate"],
            "application_ack_rate": self.twin.obs["application_ack_rate"],
            "restored": self.twin.restored,
            "terminal": self.twin.terminal,
        }

    def step(self) -> dict[str, Any]:
        if self.awaiting_approval:
            raise RuntimeError("a profile plan is awaiting human approval")
        state_text = self.router.describe(self.twin.observe())  # exactly what Decider reads
        r = self.router.step(self.twin.observe())
        entry = r.to_trace()
        entry["state_text"] = state_text
        if r.executed == "evaluate_profile_change" and self.twin.obs["profile_change_pending"]:
            if self.approve is None:
                entry["approval"] = "pending"
            else:
                ok = bool(self.approve(self.twin, str(r.tool_output)))
                entry["approval"] = "approved" if ok else "not approved"
                entry["profile_execution"] = self.twin.execute_profile_change(ok)
        entry["after"] = self._after()
        self.steps.append(entry)
        return entry

    def resolve_approval(self, approved: bool) -> dict[str, Any]:
        if not self.awaiting_approval:
            raise RuntimeError("nothing awaiting approval")
        entry = self.steps[-1]
        entry["approval"] = "approved" if approved else "not approved"
        entry["profile_execution"] = self.twin.execute_profile_change(approved)
        entry["after"] = self._after()
        return entry

    def run(self) -> dict[str, Any]:
        while not self.done:
            self.step()
        return self.result()

    def result(self) -> dict[str, Any]:
        return {"steps": self.steps, "outcome": self.twin.outcome(), "events": self.twin.events}
