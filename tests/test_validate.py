import copy
import glob
import json
import os

from simshift.validate import problems

RUNS = sorted(glob.glob(os.path.join(os.path.dirname(__file__), "..", "docs", "sample-runs", "**", "*.json"),
                        recursive=True))


def test_published_runs_are_valid():
    assert RUNS
    for path in RUNS:
        assert problems(json.load(open(path))) == [], path


def test_validator_catches_tampering():
    br = json.load(open([p for p in RUNS if p.endswith("/BR_PROFILE.json")][0]))
    off = json.load(open([p for p in RUNS if p.endswith("/OFFLINE.json")][0]))
    a = copy.deepcopy(off); a["outcome"]["restored"] = True
    b = copy.deepcopy(br); b["trace"][0]["tool"] = "simulate_retry_with_backoff"
    c = copy.deepcopy(br); c["trace"][-1]["tool_result"]["gate"]["allowed"] = False
    d = copy.deepcopy(br); d["trace"][0]["decision"]["raw"]["confidence"] = 0.9
    for bad in (a, b, c, d):
        assert problems(bad)
