import copy
import glob
import json
import os

import pytest

from simshift.simulator import SCENARIOS
from simshift.validate import problems

RUNS = sorted(glob.glob(os.path.join(os.path.dirname(__file__), "..", "docs", "sample-runs", "**", "*.json"),
                        recursive=True))


def load(name):
    return json.load(open([p for p in RUNS if p.endswith(f"orchestrated/{name}.json")][0]))


def test_published_runs_are_valid():
    assert RUNS
    for path in RUNS:
        assert problems(json.load(open(path))) == [], path


def tamper(name, fn):
    run = copy.deepcopy(load(name))
    fn(run)
    return run


@pytest.mark.parametrize("name, fn, expected", [
    ("OFFLINE", lambda r: r["outcome"].update(restored=True), "claims restored"),
    ("BR_PROFILE", lambda r: r["trace"][0].update(tool="simulate_retry_with_backoff"), "not the routed admissible"),
    ("BR_PROFILE", lambda r: r["trace"][-1]["tool_result"]["gate"].update(allowed=False), "passing gates"),
    ("BR_PROFILE", lambda r: r["trace"][0]["decision"]["raw"].update(confidence=0.9), "inconsistent"),
    ("BR_PROFILE", lambda r: r["trace"][0]["decision"]["state"].update(x=SCENARIOS["BR_PROFILE"]["hidden"]["cause"]),
     "hidden cause leaked"),
    ("BR_PROFILE", lambda r: r["trace"][2]["decision"].update(selected="escalate_or_wait", tool="defer_or_escalate")
     or r["trace"][2].update(tool="defer_or_escalate"), "route act but"),
    ("OFFLINE", lambda r: r["trace"][-1].update(decision=None, tool="simulate_retry_with_backoff", note="x"),
     "without a decision"),
    ("OFFLINE", lambda r: r["trace"][0]["decision"]["excluded"].pop("evaluate_profile_change"), "policy gives"),
    ("OFFLINE", lambda r: r["outcome"].update(forbidden_executions=1), "forbidden executions"),
    ("OFFLINE", lambda r: r["trace"].append({**r["trace"][-1], "step": 9, "decision": None, "note": "operator approved x",
                                             "tool": "prepare_guarded_profile_transition"}), "pending proposal"),
])
def test_validator_catches_each_kind_of_tampering(name, fn, expected):
    found = problems(tamper(name, fn))
    assert any(expected in p for p in found), found
