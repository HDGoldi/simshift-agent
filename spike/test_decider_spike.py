"""Spike tests. Unit tests use a fake decider; `test_decider_is_real` needs the local server."""

from __future__ import annotations

import os
import urllib.request

import pytest

from decider_spike import SCENARIOS, TOOLS, HttpDecider, allowed_actions, route


class FakeDecider:
    def __init__(self, choice: str) -> None:
        self.choice = choice

    def choose(self, state, options):
        return {"answers": {"next_tool": {"choice": self.choice, "probabilities": {self.choice: 1.0}, "confidence": 1.0}}}


def test_decider_controls_tool():
    """Flip the decider's admissible choice -> a different tool runs."""
    state = SCENARIOS["BR_PROFILE"]
    allowed, _ = allowed_actions(state)
    tools_run = {route("BR", state, FakeDecider(c)).tool for c in allowed}
    assert tools_run == {TOOLS[c].__name__ for c in allowed}
    assert len(tools_run) == len(allowed) > 1


def test_policy_filters_unavailable_operator():
    allowed, removed = allowed_actions(SCENARIOS["BR_PROFILE"])
    assert "try_allowed_operator" not in allowed
    assert "try_allowed_operator" in removed


def test_unreachable_blocks_profile_change():
    allowed, removed = allowed_actions(SCENARIOS["OFFLINE"])
    assert "evaluate_profile_change" not in allowed
    assert removed["evaluate_profile_change"] == "no reachable management path"


def test_non_admissible_choice_is_refused():
    with pytest.raises(RuntimeError):
        route("OFFLINE", SCENARIOS["OFFLINE"], FakeDecider("evaluate_profile_change"))


def _server_up() -> bool:
    try:
        urllib.request.urlopen(os.environ.get("STRANDS_DECIDER_URL", "http://127.0.0.1:8099") + "/health", timeout=3)
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _server_up(), reason="no local strands-decider server")
def test_decider_is_real():
    r = route("BR_PROFILE", SCENARIOS["BR_PROFILE"], HttpDecider())
    assert r.raw["model"].startswith("strands-decider-2B")
    assert r.choice in r.allowed
    assert abs(sum(r.probabilities.values()) - 1.0) < 1e-3
