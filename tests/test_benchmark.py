import json

import pytest

from simshift.benchmark import FAMILIES, RandomChooser, RulesChooser, make, run_one, summarize
from simshift.simulator import SCENARIOS, FleetTwin


@pytest.fixture
def generated(monkeypatch):
    for fam in FAMILIES:
        monkeypatch.setitem(SCENARIOS, f"t-{fam}", make(fam, 9000))  # removed again after the test


def test_generator_is_seeded_and_hides_the_family(generated):
    assert make("profile", 9001) == make("profile", 9001) != make("profile", 9002)
    for fam in FAMILIES:
        assert f"generated:{fam}" not in json.dumps(FleetTwin(f"t-{fam}").observe())


def test_baselines_run_through_the_gate(generated):
    rows = {name: [run_one(f"t-{fam}", fam, c) for fam in FAMILIES]
            for name, c in (("rules", RulesChooser()), ("random", RandomChooser(7)))}
    rules, rand = summarize(rows["rules"]), summarize(rows["random"])
    assert rules["correct_end_pct"] >= rand["correct_end_pct"] and rules["incidents"] == len(FAMILIES)
    assert rules["forbidden_executions"] == rand["forbidden_executions"] == 0
