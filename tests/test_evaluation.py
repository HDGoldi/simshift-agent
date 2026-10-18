"""Evaluation harness tests (no model server, no AWS)."""

from __future__ import annotations

import json

import pytest

from agent.incident import Incident
from evaluation.baselines import RandomChooser, RulesChooser
from evaluation.benchmark import aggregate, approve_all, run_strategy, score_incident, to_markdown
from evaluation.dataset import FAMILIES, generate, make
from simulator.scenarios import describe


def test_dataset_is_reproducible_and_splits_disjoint():
    assert generate("heldout", 3) == generate("heldout", 3)
    dev = {f["id"] for f in generate("dev", 5)}
    held = {f["id"] for f in generate("heldout", 5)}
    assert not dev & held
    assert len(held) == 5 * len(FAMILIES)


@pytest.mark.parametrize("family", list(FAMILIES))
def test_no_label_leaks_into_state_text(family):
    fx = make(family, 9000)
    text = describe(fx["observable"]) + json.dumps(fx["observable"])
    lab = fx["evaluator_only"]
    # family names are ordinary words ("firmware"); the leak to guard against is the labels themselves
    assert lab["true_cause"] not in text
    assert lab["preferred_first"] not in text
    assert "evaluator_only" not in fx["observable"]


@pytest.mark.parametrize("family", list(FAMILIES))
def test_preferred_path_resolves_every_family(family):
    """An oracle that always takes the preferred first step, then escalates, must succeed."""
    fx = make(family, 9001)
    seq = [fx["evaluator_only"]["preferred_first"], "escalate_or_wait"]

    class Oracle:
        i = 0

        def choose(self, state, question, criteria):
            from patterns.capability_aware_router import Decision

            c = seq[min(self.i, 1)]
            self.i += 1
            c = c if c in criteria else next(iter(criteria))
            return Decision(choice=c, probabilities={c: 1.0}, confidence=1.0)

    res = Incident(fx, Oracle(), approve=approve_all).run()
    assert score_incident(fx, res)["resolved_correctly"], res["outcome"]


def test_preferred_first_is_always_admissible():
    from decider.recovery_decisions import build_router

    for fx in generate("heldout", 5):
        allowed, _ = build_router(RandomChooser()).admissible(fx["observable"])
        assert fx["evaluator_only"]["preferred_first"] in allowed, fx["id"]


def test_rules_and_random_run_end_to_end():
    fixtures = generate("dev", 2)
    for name in ("rules", "random"):
        out = run_strategy(name, fixtures, progress=False)
        s = out["summary"]
        assert s["n"] == len(fixtures) and s["forbidden_executions"] == 0
    md = to_markdown({"created": "t", "split": "dev", "per_family": 2, "seed_range": "x",
                      "decider_model": "n/a", "decider_device": "n/a", "hardware": "n/a"},
                     {"rules": out})
    assert "| Resolved correctly (%) |" in md


def test_aggregate_buckets():
    rows = [score_incident(fx, Incident(fx, RulesChooser(), approve=approve_all).run()) for fx in generate("dev", 1)]
    s = aggregate(rows, 1.0)
    assert s["high_conf_n"] == len(rows)  # rules always report confidence 1.0
