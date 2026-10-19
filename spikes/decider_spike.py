"""Spike used on 2026-10-18 to validate the Strands Decider API before building the agent.

Runs the in-process engine (not the HTTP server) on an illustrative Brazil state,
and prints the raw choice/noul answers and latencies. Run it with the strands-decider venv:
    python spikes/decider_spike.py mlx|cpu
"""
import json, sys, time
from strands_decider.infer import load_engine
from strands_decider.schema import SystemOneRequest

CKPT = "StrandsAgents/strands-decider-2B-qwen3.5-v1-2610"
device = sys.argv[1] if len(sys.argv) > 1 else "mlx"

STATE = {
    "incident": "Persistent cellular attach failures",
    "country": "BR",
    "affected_devices": 3200,
    "attach_success_rate": 0.04,
    "active_profile": "profile_A",
    "allowed_alternative_operator_available": False,
    "alternative_profile_installed": True,
    "management_path_reachable": True,
    "recent_firmware_change": False,
    "attempted_retries": 3,
}
CHOICE = {"next_recovery_step": {
    "type": "choice",
    "instructions": "Choose the most useful next permitted recovery or diagnostic step. Do not assume that an unverified recovery path works.",
    "criteria": {
        "retry_connection": "Bounded backoff on the active subscription",
        "investigate_device": "Gather modem or device evidence",
        "evaluate_profile_change": "Investigate feasibility of a managed profile transition; do not execute it",
        "escalate_or_wait": "Defer or request more evidence/human review",
    },
}}
NOUL = {"evidence_sufficient": {
    "type": "noul",
    "instructions": "Is current evidence sufficient to recommend a next diagnostic or recovery step?",
}}

t0 = time.perf_counter()
engine = load_engine(CKPT, device=device)
print(f"cold_load_s={time.perf_counter() - t0:.2f}")

def run(questions):
    t = time.perf_counter()
    r = engine.evaluate(SystemOneRequest(state=STATE, questions=questions))
    return r, (time.perf_counter() - t) * 1000

r, ms = run(CHOICE); print(f"first_choice_ms={ms:.1f}"); print(json.dumps(r.model_dump(), indent=1))
lat = [run(CHOICE)[1] for _ in range(5)]
print("warm_choice_ms=", [round(x, 1) for x in lat], "median=", round(sorted(lat)[2], 1))
r, ms = run(NOUL); print(f"noul_ms={ms:.1f}"); print(json.dumps(r.model_dump(), indent=1))
r, ms = run({**CHOICE, **NOUL}); print(f"both_ms={ms:.1f}"); print(json.dumps(r.model_dump(), indent=1))
