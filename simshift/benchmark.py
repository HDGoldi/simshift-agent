"""Benchmark: which chooser picks the next recovery tool best? Synthetic, seeded, reproducible.

Every chooser answers the same typed question through the same CapabilityAwareRouter, policy filter and
profile gate, so only the choice step differs:
  rules    a hand-written runbook over the observable state (domain rules, not fitted to the generator)
  random   uniform over the admissible options
  decider  Strands Decider 2B (live server)
  bedrock  an LLM on Bedrock asked to name one option (no probabilities, so it always "acts")

    python -m simshift.benchmark --per-family 10 --choosers rules,random,decider,bedrock --stamp 2026-10-18

Incidents come from 6 families with seeds 9000+; none of them were used to write the option descriptions
or policy rules (those were tuned on the 6 hand-written scenarios). Approvals are auto-granted here only,
so a correct profile change can complete; every other check still applies.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import time

from strands import Agent
from strands.models import BedrockModel
from strands.types.exceptions import MaxTokensReachedException

from patterns.capability_aware_router.router import DeciderClient

from .agent import BEDROCK_MODEL, REGION, Incident
from .simulator import SCENARIOS

# family -> (preferred first action, acceptable first actions, correct end state)
FAMILIES = {
    "operator": ("try_allowed_operator", {"try_allowed_operator", "investigate_data_path"}, "restored"),
    "profile": ("investigate_device", {"investigate_device", "investigate_data_path"}, "restored"),
    "application": ("investigate_data_path", {"investigate_data_path"}, "escalated"),
    "unreachable": ("escalate_or_wait", {"escalate_or_wait", "investigate_data_path"}, "escalated"),
    "firmware": ("investigate_device", {"investigate_device"}, "escalated"),
    "transient": ("retry_connection", {"retry_connection"}, "restored"),
}
COUNTRIES = ["DE", "BR", "JP", "US", "MX", "IN", "ZA", "FR", "KR", "CA"]


def make(family: str, seed: int) -> dict:
    """One incident in the twin's scenario schema. Signals are noisy so no single field gives the answer away."""
    r = random.Random(f"{family}:{seed}")
    c = r.choice(COUNTRIES)
    n1, n2, n3 = f"{c}-NET-1", f"{c}-NET-2", f"{c}-NET-3"
    s = {"title": f"generated {family} incident", "country": c, "devices": r.choice([450, 900, 2100, 3200, 5400, 8400]),
         "serving_operator": n1, "active_profile": "profile_A",
         "profiles": {"profile_A": {"operators": [n1]}, "profile_B": {"operators": [n2]}},
         "operators_in_coverage": [n1, n2], "networks": {n1: "up", n2: "up"}, "ingestion_healthy": True,
         "management": {"up": True, "via_cellular": True, "path": "cellular IP via active profile"},
         "euicc": {"supports_profile_enable": True, "rollback_supported": True}, "owner_allows_profile_switch": True,
         "recent_firmware_change": r.random() < 0.25, "attempted_retries": r.randint(0, 2),
         "attach_trend": r.choice(["flat", "flat", "falling"])}
    if family == "operator":
        s["profiles"]["profile_A"]["operators"] = [n1, n3]
        s["operators_in_coverage"] += [n3]
        s["networks"].update({n1: "down", n3: "up"})
        s["incident"] = r.choice(["Attach failures on primary network", "Cohort losing registration"])
    elif family == "profile":
        s["networks"][n1] = "down"
        s["management"] = {"up": True, "via_cellular": False, "path": "gateway Wi-Fi (non-cellular IP)"}
        s["attempted_retries"] = r.randint(1, 3)
        s["incident"] = r.choice(["Persistent cellular attach failures", "Cohort losing registration"])
    elif family == "application":
        s["ingestion_healthy"] = False
        s["incident"] = r.choice(["Telemetry not arriving", "Cohort telemetry missing"])
    elif family == "unreachable":
        s.update(device_powered=False, operators_in_coverage=[], management={"up": False, "via_cellular": False, "path": None})
        s["incident"] = r.choice(["Devices silent; no heartbeat", "Remote cohort silent"])
    elif family == "firmware":
        s.update(firmware_fault=True, recent_firmware_change=r.random() < 0.8,
                 attach_trend=r.choice(["flapping", "flapping", "flat"]))
        s["incident"] = r.choice(["Devices dropping off the network repeatedly", "Cohort losing registration"])
    elif family == "transient":
        s.update(transient_congestion=True, attempted_retries=r.randint(0, 1),
                 attach_trend=r.choice(["improving", "improving", "flat"]))
        s["incident"] = r.choice(["Short burst of attach failures", "Cohort losing registration"])
    s["hidden"] = {"cause": f"generated:{family}", "best_actions": sorted(FAMILIES[family][1])}
    return s


class _OneHot:
    def _answer(self, choice: str, options: dict) -> dict:
        return {"choice": choice, "probabilities": {o: float(o == choice) for o in options}, "confidence": 1.0}


class RulesChooser(_OneHot):
    """What a NOC runbook might say. Written from domain knowledge, not fitted to the generator's numbers."""

    def choose(self, state, instructions, options, name="next_tool"):
        resets = state["diagnostics"].get("device", {}).get("modem_resets_per_day", 0)
        if state["app_ack_rate"] < 0.95 <= state["attach_success_rate"]:
            order = ["investigate_data_path"]
        elif state["attach_success_rate"] == 0 and not state["management_path_reachable"]:
            order = ["escalate_or_wait"]
        elif state["other_operator_allowed_on_active_profile"]:
            order = ["try_allowed_operator"]
        elif state["recent_firmware_change"] or state.get("attach_trend") == "flapping" or resets > 5:
            order = ["investigate_device"]
        elif state.get("attach_trend") == "improving" or state["attach_success_rate"] > 0.2:
            order = ["retry_connection"]
        else:
            order = ["investigate_device", "evaluate_profile_change"]
        order += ["evaluate_profile_change", "investigate_device", "investigate_data_path", "escalate_or_wait"]
        return self._answer(next(o for o in order if o in options), options)


class RandomChooser(_OneHot):
    def __init__(self, seed: int):
        self.r = random.Random(seed)

    def choose(self, state, instructions, options, name="next_tool"):
        return self._answer(self.r.choice(sorted(options)), options)


class BedrockChooser(_OneHot):
    """Bedrock names one option. An unparseable answer raises ValueError, which the router turns into the fallback;
    it is counted, not hidden."""

    def __init__(self):
        self.llm = BedrockModel(model_id=BEDROCK_MODEL, region_name=REGION, max_tokens=512)
        self.tokens = {"inputTokens": 0, "outputTokens": 0}
        self.unparseable, self.samples = 0, []  # samples: the first unparseable answers, kept for the record

    def choose(self, state, instructions, options, name="next_tool"):
        prompt = (f"{instructions}\nState: {json.dumps(state)}\nOptions:\n"
                  + "\n".join(f"- {o}: {d}" for o, d in options.items())
                  + "\nAnswer with exactly one option name and nothing else.")
        t0 = time.perf_counter()
        try:
            res = Agent(model=self.llm, tools=[], callback_handler=None)(prompt)
        except MaxTokensReachedException as e:
            self.unparseable += 1
            self.samples.append("(cut off at the output token limit)")
            raise ValueError("Bedrock answer hit the token limit") from e
        ms = round((time.perf_counter() - t0) * 1000, 1)
        for k in self.tokens:
            self.tokens[k] += res.metrics.accumulated_usage.get(k, 0)
        text = str(res).strip()
        named = [o for o in options if o in text]  # lenient: accept any answer that names exactly one option
        answer = text.strip("`'\". ") if text.strip("`'\". ") in options else named[0] if len(named) == 1 else None
        if answer is None:
            self.unparseable += 1
            self.samples.append(text[:200])
            raise ValueError(f"unparseable Bedrock answer {text[:60]!r}")
        return {**self._answer(answer, options), "client_latency_ms": ms, "model": BEDROCK_MODEL}


def run_one(sid: str, family: str, chooser) -> dict:
    inc = Incident(sid, approve=True, decider=chooser, use_bedrock=False)  # approval auto-granted: eval only
    calls = []
    original = chooser.choose

    def timed(*a, **k):
        t0 = time.perf_counter()
        try:
            return original(*a, **k)
        finally:
            calls.append(round((time.perf_counter() - t0) * 1000, 1))

    chooser.choose = timed
    try:
        while not inc.done:
            inc.step()
    finally:
        chooser.choose = original
    preferred, acceptable, terminal = FAMILIES[family]
    first = inc.trace[0]["decision"]
    escalated = inc.trace[-1]["tool"] == "defer_or_escalate"
    end = "restored" if inc.twin.service_restored() else "escalated" if escalated else "stuck"
    unnecessary = inc.twin.profile_changes if family != "profile" else max(0, inc.twin.profile_changes - 1)
    o = inc.outcome()
    return {"incident": sid, "family": family,
            "first_choice": (first["raw"] or {}).get("choice"), "first_action": first["selected"],
            "first_choice_preferred": (first["raw"] or {}).get("choice") == preferred,
            "first_action_acceptable": first["selected"] in acceptable,
            "end": end, "correct_end": end == terminal, "unnecessary_profile_changes": unnecessary,
            "correct_without_collateral": end == terminal and unnecessary == 0,
            "steps": o["steps"], "simulated_minutes": o["simulated_minutes"],
            "forbidden_executions": o["forbidden_executions"], "chooser_ms": calls,
            "trace": [{"decision": t["decision"], "tool": t["tool"], "note": t.get("note")} for t in inc.trace]}


def summarize(rows: list[dict]) -> dict:
    n = len(rows)
    ms = [m for r in rows for m in r["chooser_ms"]]
    pct = lambda k: round(100 * sum(r[k] for r in rows) / n, 1)  # noqa: E731
    q = statistics.quantiles(ms, n=20) if len(ms) > 1 else [0] * 19
    return {"incidents": n, "first_choice_preferred_pct": pct("first_choice_preferred"),
            "first_action_acceptable_pct": pct("first_action_acceptable"), "correct_end_pct": pct("correct_end"),
            "correct_without_collateral_pct": pct("correct_without_collateral"),
            "unnecessary_profile_changes": sum(r["unnecessary_profile_changes"] for r in rows),
            "forbidden_executions": sum(r["forbidden_executions"] for r in rows),
            "mean_steps": round(statistics.mean(r["steps"] for r in rows), 2),
            "mean_simulated_minutes": round(statistics.mean(r["simulated_minutes"] for r in rows), 1),
            "chooser_calls": len(ms), "latency_p50_ms": round(statistics.median(ms), 1) if ms else 0,
            "latency_p95_ms": round(q[18], 1),
            "by_family_correct_end_pct": {f: round(100 * statistics.mean(r["correct_end"] for r in rows if r["family"] == f), 1)
                                          for f in FAMILIES}}


def markdown(meta: dict, summaries: dict) -> str:
    rows = [("Incidents", "incidents"), ("First choice = preferred (%)", "first_choice_preferred_pct"),
            ("First action acceptable (%)", "first_action_acceptable_pct"), ("Correct end state (%)", "correct_end_pct"),
            ("Correct, no unnecessary eSIM change (%)", "correct_without_collateral_pct"),
            ("Unnecessary profile changes", "unnecessary_profile_changes"),
            ("Forbidden executions (audited)", "forbidden_executions"), ("Mean steps", "mean_steps"),
            ("Mean simulated minutes", "mean_simulated_minutes"), ("Chooser calls", "chooser_calls"),
            ("Chooser latency p50 (ms)", "latency_p50_ms"), ("Chooser latency p95 (ms)", "latency_p95_ms")]
    cs = list(summaries)
    out = [f"# SIMShift benchmark ({meta['stamp']})", "",
           f"{meta['per_family']} incidents per family x {len(FAMILIES)} families, seeds {meta['seeds']}. "
           f"Synthetic twin. Approvals auto-granted (eval only). Hardware: {meta['hardware']}.", "",
           "| Metric | " + " | ".join(cs) + " |", "|---|" + "---:|" * len(cs)]
    out += [f"| {label} | " + " | ".join(str(summaries[c][k]) for c in cs) + " |" for label, k in rows]
    out += ["", "Correct end state by family (%):", "", "| Family | " + " | ".join(cs) + " |", "|---|" + "---:|" * len(cs)]
    out += [f"| {f} | " + " | ".join(str(summaries[c]["by_family_correct_end_pct"][f]) for c in cs) + " |" for f in FAMILIES]
    if "bedrock" in meta:
        out += ["", f"Bedrock ({BEDROCK_MODEL}): {meta['bedrock']['tokens']} tokens, "
                    f"{meta['bedrock']['unparseable']} answers without exactly one option name or cut off at the "
                    f"512-token output limit; each was routed to the fallback."]
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-family", type=int, default=10)
    ap.add_argument("--choosers", default="rules,random,decider,bedrock")
    ap.add_argument("--stamp", required=True, help="label for the result files, e.g. the date")
    ap.add_argument("--hardware", default="Decider: MLX on Apple M4 Max laptop; Bedrock: eu-central-1")
    ap.add_argument("--out-dir", default="docs/benchmark")
    a = ap.parse_args()
    incidents = []
    for fam in FAMILIES:
        for i in range(a.per_family):
            sid = f"gen-{fam}-{9000 + i}"
            SCENARIOS[sid] = make(fam, 9000 + i)  # ponytail: registers generated incidents in the global table
            incidents.append((sid, fam))
    meta = {"stamp": a.stamp, "per_family": a.per_family, "seeds": f"9000..{9000 + a.per_family - 1}",
            "hardware": a.hardware, "decider_url": os.environ.get("DECIDER_URL", "http://127.0.0.1:8099")}
    results, summaries = {}, {}
    for name in a.choosers.split(","):
        chooser = {"rules": RulesChooser, "random": lambda: RandomChooser(7), "bedrock": BedrockChooser,
                   "decider": lambda: DeciderClient(meta["decider_url"])}[name]()
        results[name] = [run_one(sid, fam, chooser) for sid, fam in incidents]
        summaries[name] = summarize(results[name])
        if name == "bedrock":
            meta["bedrock"] = {"model": BEDROCK_MODEL, "tokens": chooser.tokens, "unparseable": chooser.unparseable,
                               "unparseable_samples": chooser.samples[:5]}
        print(name, json.dumps(summaries[name]))
    os.makedirs(a.out_dir, exist_ok=True)
    base = os.path.join(a.out_dir, f"benchmark-{a.stamp}")
    with open(base + ".json", "w") as f:
        json.dump({"meta": meta, "summary": summaries, "results": results}, f, indent=1)
    with open(base + ".md", "w") as f:
        f.write(markdown(meta, summaries))
    print(open(base + ".md").read())
