import glob
import json
import os

import pytest

from simshift.benchmark import FAMILIES, BedrockChooser, RandomChooser, RulesChooser, make, run_one, summarize
from simshift.simulator import SCENARIOS, FleetTwin

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


def derive(row: dict) -> dict:
    """Re-derives a row's scoring from its stored trace and events, independently of the stored booleans."""
    from simshift.benchmark import EVIDENCE
    from simshift.simulator import RESTORED_THRESHOLD
    last = row["trace"][-1]
    rates = last["rates_after"]
    restored = rates["attach_success_rate"] >= RESTORED_THRESHOLD and rates["app_ack_rate"] >= RESTORED_THRESHOLD
    end = "restored" if restored else "escalated" if last["tool"] == "defer_or_escalate" else "stuck"
    fam = row["family"]
    kinds = {e["kind"] for e in row["events"]}
    evidence = f"diagnostics_{EVIDENCE[fam]}" in kinds if fam in EVIDENCE else True
    changes = sum(e["kind"] == "eim_enable_profile" and e.get("ok") for e in row["events"])
    unnecessary = changes if fam != "profile" else max(0, changes - 1)
    preferred, acceptable, terminal = FAMILIES[fam]
    first = row["trace"][0]["decision"]
    correct = end == terminal and evidence
    return {"end": end, "evidence_collected": evidence, "unnecessary_profile_changes": unnecessary,
            "correct_end": correct, "correct_without_collateral": correct and unnecessary == 0,
            "first_choice_preferred": (first["raw"] or {}).get("choice") == preferred,
            "first_action_acceptable": first["selected"] in acceptable, "steps": len(row["trace"])}


@pytest.mark.parametrize("path", PUBLISHED)
def test_published_benchmark_is_reproducible_from_its_records(path, monkeypatch):
    """Every scored field is re-derived from the stored trace and events, so editing a score (and its summary)
    without editing the trace fails here."""
    from simshift.validate import problems
    d = json.load(open(path))
    for chooser, rows in d["results"].items():
        assert summarize(rows) == d["summary"][chooser], chooser  # headline numbers come from the stored rows
        for row in rows:
            derived = derive(row)
            assert {k: row[k] for k in derived} == derived, (chooser, row["incident"])
            fam, seed = row["incident"].split("-")[1], int(row["incident"].split("-")[2])
            monkeypatch.setitem(SCENARIOS, row["incident"], make(fam, seed))  # regenerate: seeds are deterministic
            run = {"scenario": row["incident"], "trace": row["trace"], "events": row["events"], "outcome": row["outcome"]}
            assert problems(run) == [], (chooser, row["incident"], problems(run))
