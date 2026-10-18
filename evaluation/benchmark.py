"""SIMShift benchmark: same incidents, same policy, same twin; only the chooser differs.

    python -m evaluation.benchmark --strategies rules,random            # fast, no model
    python -m evaluation.benchmark --strategies rules,random,decider    # needs `make serve-decider`
    python -m evaluation.benchmark --strategies decider,bedrock          # needs Bedrock access
    python -m evaluation.benchmark --split dev --per-family 3

Profile plans are auto-approved during evaluation (standing in for a human who approves every
plan that passes the guards); the guards themselves still apply. Results are written to
evaluation/results/<timestamp>-<split>.{json,md}. Nothing here is a real-world measurement.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Any

from agent.incident import Incident
from evaluation.baselines import BedrockChooser, RandomChooser, RulesChooser
from evaluation.dataset import FAMILIES, generate

RESULTS = Path(__file__).parent / "results"
LOW_CONF = 0.3  # bucket boundary for reporting only; not a tuned threshold


def approve_all(_twin, _plan) -> bool:
    return True


def make_chooser(name: str) -> Any:
    if name == "rules":
        return RulesChooser()
    if name == "random":
        return RandomChooser(seed=0)
    if name == "decider":
        from patterns.capability_aware_router import HttpDeciderClient

        c = HttpDeciderClient()
        c.health()  # fail fast if the server is down
        return c
    if name == "bedrock":
        return BedrockChooser()
    raise ValueError(name)


def score_incident(fx: dict[str, Any], res: dict[str, Any]) -> dict[str, Any]:
    lab = fx["evaluator_only"]
    o = res["outcome"]
    steps = res["steps"]
    first = steps[0]["choice"] if steps else None
    if lab["correct_terminal"] == "escalated":
        correct = o["escalated"] and o["profile_changes"] == 0
    else:
        correct = o["restored"]
    decided = [s for s in steps if s.get("choice")]
    return {
        "id": fx["id"],
        "family": lab["family"],
        "first_choice": first,
        "first_confidence": steps[0]["confidence"] if steps else None,
        "first_preferred": first == lab["preferred_first"],
        "first_acceptable": first in lab["acceptable_first"],
        "resolved_correctly": correct,
        "steps": len(steps),
        "downtime_minutes": o["downtime_minutes"],
        "profile_changes": o["profile_changes"],
        "unnecessary_profile_changes": o["unnecessary_profile_changes"],
        "blocked_actions": o["blocked_actions"],
        "forbidden_executions": o["forbidden_executions"],
        "decisions": len(decided),
        "latencies_ms": [s["decider_latency_ms"] for s in decided if s.get("decider_latency_ms") is not None],
        "trace": [{"choice": s["choice"], "confidence": s["confidence"], "removed": list(s["removed"]),
                   "approval": s.get("approval")} for s in steps],
    }


def _pct(xs: list[bool]) -> float:
    return round(100 * sum(xs) / len(xs), 1) if xs else 0.0


def _q(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(q * len(xs)))], 1)


def aggregate(rows: list[dict[str, Any]], wall_s: float) -> dict[str, Any]:
    lat = [x for r in rows for x in r["latencies_ms"]]
    conf = [r for r in rows if r["first_confidence"] is not None]
    low = [r for r in conf if r["first_confidence"] < LOW_CONF]
    high = [r for r in conf if r["first_confidence"] >= LOW_CONF]
    return {
        "n": len(rows),
        "first_tool_preferred_pct": _pct([r["first_preferred"] for r in rows]),
        "first_tool_acceptable_pct": _pct([r["first_acceptable"] for r in rows]),
        "resolved_correctly_pct": _pct([r["resolved_correctly"] for r in rows]),
        "unnecessary_profile_changes": sum(r["unnecessary_profile_changes"] for r in rows),
        "profile_changes": sum(r["profile_changes"] for r in rows),
        "blocked_actions": sum(r["blocked_actions"] for r in rows),
        "forbidden_executions": sum(r["forbidden_executions"] for r in rows),
        "mean_steps": round(statistics.mean(r["steps"] for r in rows), 2),
        "mean_downtime_min": round(statistics.mean(r["downtime_minutes"] for r in rows), 1),
        "decisions": sum(r["decisions"] for r in rows),
        "latency_p50_ms": _q(lat, 0.5),
        "latency_p95_ms": _q(lat, 0.95),
        "low_conf_n": len(low),
        "low_conf_first_acceptable_pct": _pct([r["first_acceptable"] for r in low]),
        "high_conf_n": len(high),
        "high_conf_first_acceptable_pct": _pct([r["first_acceptable"] for r in high]),
        "wall_seconds": round(wall_s, 1),
        "by_family": {
            f: {
                "n": len(fr),
                "first_acceptable_pct": _pct([r["first_acceptable"] for r in fr]),
                "resolved_correctly_pct": _pct([r["resolved_correctly"] for r in fr]),
            }
            for f in FAMILIES
            if (fr := [r for r in rows if r["family"] == f])
        },
    }


def run_strategy(name: str, fixtures: list[dict[str, Any]], progress: bool = True) -> dict[str, Any]:
    chooser = make_chooser(name)
    rows = []
    t0 = time.perf_counter()
    for i, fx in enumerate(fixtures, 1):
        res = Incident(fx, chooser, approve=approve_all, max_steps=5).run()
        rows.append(score_incident(fx, res))
        if progress:
            r = rows[-1]
            print(f"  [{name}] {i}/{len(fixtures)} {fx['id']}: first={r['first_choice']} "
                  f"ok={r['resolved_correctly']}", flush=True)
    summary = aggregate(rows, time.perf_counter() - t0)
    if isinstance(chooser, BedrockChooser):
        summary["bedrock_input_tokens"] = chooser.input_tokens
        summary["bedrock_output_tokens"] = chooser.output_tokens
        summary["bedrock_model"] = chooser.model_id
    return {"summary": summary, "incidents": rows}


def to_markdown(meta: dict[str, Any], results: dict[str, Any]) -> str:
    names = list(results)
    rows = [
        ("Incidents", "n"),
        ("First tool = preferred (%)", "first_tool_preferred_pct"),
        ("First tool acceptable (%)", "first_tool_acceptable_pct"),
        ("Resolved correctly (%)", "resolved_correctly_pct"),
        ("Unnecessary profile changes", "unnecessary_profile_changes"),
        ("Forbidden executions", "forbidden_executions"),
        ("Mean steps", "mean_steps"),
        ("Mean simulated downtime (min)", "mean_downtime_min"),
        ("Decisions made", "decisions"),
        ("Decision latency p50 (ms)", "latency_p50_ms"),
        ("Decision latency p95 (ms)", "latency_p95_ms"),
    ]
    out = [f"# SIMShift benchmark - {meta['split']} split",
           "",
           (f"{meta['created']} · {meta['per_family']} incidents per family × {len(FAMILIES)} families · "
           f"seeds {meta['seed_range']} · approvals auto-granted (guards still apply) · **synthetic data**"),
           f"Decider: `{meta['decider_model']}` on `{meta['decider_device']}`. Hardware: {meta['hardware']}.",
           "",
           "| Metric | " + " | ".join(names) + " |",
           "|---|" + "---:|" * len(names)]
    for label, key in rows:
        out.append(f"| {label} | " + " | ".join(str(results[n]["summary"].get(key, "")) for n in names) + " |")
    out += ["", "## First tool acceptable, by family (%)", "",
            "| Family | " + " | ".join(names) + " |", "|---|" + "---:|" * len(names)]
    for f in FAMILIES:
        out.append(f"| {f} | " + " | ".join(
            str(results[n]["summary"]["by_family"].get(f, {}).get("first_acceptable_pct", "")) for n in names) + " |")
    if "decider" in results:
        s = results["decider"]["summary"]
        out += ["", "## Decider confidence buckets (first step)", "",
                f"- confidence < {LOW_CONF}: n={s['low_conf_n']}, acceptable {s['low_conf_first_acceptable_pct']}%",
                f"- confidence ≥ {LOW_CONF}: n={s['high_conf_n']}, acceptable {s['high_conf_first_acceptable_pct']}%"]
    return "\n".join(out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="heldout", choices=["dev", "heldout"])
    ap.add_argument("--per-family", type=int, default=5)
    ap.add_argument("--strategies", default="rules,random,decider")
    a = ap.parse_args()

    fixtures = generate(a.split, a.per_family)
    results: dict[str, Any] = {}
    for name in a.strategies.split(","):
        print(f"== {name}", flush=True)
        results[name] = run_strategy(name, fixtures)

    meta: dict[str, Any] = {
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "split": a.split,
        "per_family": a.per_family,
        "seed_range": f"{fixtures[0]['id'].split('-')[1]}..+{a.per_family - 1}",
        "decider_model": "n/a",
        "decider_device": "n/a",
        "hardware": "n/a",
    }
    if "decider" in results:
        import os
        import platform

        from patterns.capability_aware_router import HttpDeciderClient

        h = HttpDeciderClient().health()
        meta |= {"decider_model": h.get("model"), "decider_device": h.get("device"),
                 "hardware": f"{platform.machine()}, {os.cpu_count()} vCPU, no GPU" if h.get("device") == "cpu"
                 else platform.machine()}

    RESULTS.mkdir(exist_ok=True)
    stem = RESULTS / f"{meta['created'].replace(':', '')}-{a.split}"
    stem.with_suffix(".json").write_text(json.dumps({"meta": meta, "results": results}, indent=2))
    md = to_markdown(meta, results)
    stem.with_suffix(".md").write_text(md)
    print("\n" + md)
    print(f"wrote {stem}.json and .md")


if __name__ == "__main__":
    main()
