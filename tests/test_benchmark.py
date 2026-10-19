import glob
import json
import os

import pytest

from simshift.benchmark import FAMILIES, BedrockChooser, RandomChooser, RulesChooser, make, run_one, summarize
from simshift.simulator import SCENARIOS, FleetTwin
from simshift.validate import step_problems

PUBLISHED = sorted(glob.glob(os.path.join(os.path.dirname(__file__), "..", "docs", "benchmark", "*.json")))


@pytest.fixture
def generated(monkeypatch):
    for fam in FAMILIES:
        monkeypatch.setitem(SCENARIOS, f"t-{fam}", make(fam, 9000))  # removed again after the test


def test_generator_is_seeded_and_hides_the_family(generated):
    assert make("profile", 9001) == make("profile", 9001) != make("profile", 9002)
    for fam in FAMILIES:
        assert f"generated:{fam}" not in json.dumps(FleetTwin(f"t-{fam}").observe())


def test_baseline_scores_on_a_fixed_seed(generated):
    rows = {name: [run_one(f"t-{fam}", fam, c) for fam in FAMILIES]
            for name, c in (("rules", RulesChooser()), ("random", RandomChooser(7)))}
    rules, rand = summarize(rows["rules"]), summarize(rows["random"])
    assert rules["by_family_correct_end_pct"] == dict.fromkeys(FAMILIES, 100.0)
    assert rand["correct_end_pct"] < rules["correct_end_pct"]
    assert rules["forbidden_executions"] == rand["forbidden_executions"] == 0


def test_blind_escalation_is_not_a_correct_diagnosis(generated):
    class Escalate:
        def choose(self, state, instructions, options, name="next_tool"):
            return {"choice": "escalate_or_wait", "probabilities": {o: float(o == "escalate_or_wait") for o in options},
                    "confidence": 1.0}
    for fam, correct in (("application", False), ("firmware", False), ("unreachable", True)):
        r = run_one(f"t-{fam}", fam, Escalate())
        assert r["end"] == "escalated" and r["correct_end"] is correct, fam


def test_bedrock_confidence_becomes_a_consistent_distribution():
    from patterns.capability_aware_router.router import inconsistent
    b = BedrockChooser.__new__(BedrockChooser)
    b.unparseable, b.samples = 0, []
    opts = dict.fromkeys(["a", "b", "c", "d"], "")
    for c in (0.0, 0.3, 1.0):
        ans = b._with_confidence(f'{{"choice": "b", "confidence": {c}}}', opts)
        assert inconsistent(ans, opts) is None and abs(ans["confidence"] - c) < 1e-9
    with pytest.raises(ValueError):
        b._with_confidence('{"choice": "zzz", "confidence": 0.9}', opts)
    assert b.unparseable == 1


@pytest.mark.parametrize("path", PUBLISHED)
def test_published_benchmark_is_reproducible_from_its_rows(path):
    d = json.load(open(path))
    for chooser, rows in d["results"].items():
        assert summarize(rows) == d["summary"][chooser], chooser  # headline numbers come from the stored rows
        for row in rows:
            prev = None
            for t in row["trace"]:
                assert step_problems(t, prev) == [], (chooser, row["incident"])
