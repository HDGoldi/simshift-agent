"""Mechanical checks over saved run traces, so no published run can claim more than its own events show.

    python -m simshift.validate docs/sample-runs/*.json
"""
from __future__ import annotations

import json
import sys

from patterns.capability_aware_router.router import ReplayDecider, inconsistent

from .agent import TOOLS, Incident, finish, recorded_answers
from .policy import _DELIVERED as DELIVERED
from .policy import FALLBACK, OPTIONS, exclusions, only_on
from .simulator import RESTORED_THRESHOLD, SCENARIOS, idempotency_key


def step_problems(t: dict, prev_gate: dict | None, hidden: str | None = None) -> list[str]:
    """Checks one recorded step. Also used on the benchmark rows, which keep only decision, tool and note."""
    out, d, at = [], t["decision"], f"step {t.get('step', '?')}"
    if d is None:  # no model decision: an escalation, or a human approving the proposal the previous step left
        approval = (t.get("note") or "").startswith("operator approved") and t["tool"] == TOOLS["evaluate_profile_change"]
        if t["tool"] != TOOLS["escalate_or_wait"] and not approval:
            out.append(f"{at}: a step without a decision must be an escalation or a human approval")
        if approval and not (prev_gate and prev_gate["failed"] == ["human_approval"]
                             and prev_gate["proposal_id"] in t["note"]):
            out.append(f"{at}: approval step does not answer a pending proposal from the previous step")
        return out
    excluded = {k: v for k, v in exclusions(d["state"]).items() if k != FALLBACK}
    if excluded != d["excluded"] or set(d["eligible"]) != set(OPTIONS) - set(excluded):
        out.append(f"{at}: recorded options differ from what the policy gives for the recorded state")
    if t["tool"] != TOOLS[d["selected"]] or d["selected"] not in d["eligible"]:
        out.append(f"{at}: executed tool {t['tool']} is not the routed admissible option {d['selected']}")
    raw = d["raw"] or {}
    if "choice" in raw:
        if d["route"] == "act" and d["selected"] != raw["choice"]:
            out.append(f"{at}: route act but the selected option is not the Decider choice")
        if raw["choice"] in d["eligible"] and (bad := inconsistent(raw, d["eligible"])):
            out.append(f"{at}: recorded Decider answer is inconsistent: {bad}")
    if hidden and hidden in json.dumps(d["state"]):
        out.append(f"{at}: hidden cause leaked into the state sent to Decider")
    return out


def _gate(t: dict) -> dict | None:
    return t["tool_result"].get("gate") if isinstance(t.get("tool_result"), dict) else None


RESTORED_RATES = ("attach_success_rate", "data_session_rate", "app_ack_rate")


def _expected_path(ev: dict, nxt: dict, profiles: dict) -> list[str] | None:
    """The profile-switch path the event log implies for an executed enable `ev`; `nxt` is the event after it."""
    restored = all(ev["rates"][k] >= RESTORED_THRESHOLD for k in RESTORED_RATES)  # from the rates, not the flag
    if ev["result_reported"]:
        if restored:
            return list(DELIVERED) + ["RESULT_REPORTED", "VERIFYING", "SUCCEEDED"]
        if nxt.get("kind") != "eim_rollback" or (nxt["ok"] and nxt.get("to_profile") != ev["from_profile"]):
            return None  # a failed, reported switch must be followed by a rollback to the profile it replaced
        return list(DELIVERED) + ["RESULT_REPORTED", "VERIFYING", "FAILED", "ROLLED_BACK" if nxt["ok"] else "ROLLBACK_FAILED"]
    proven = (restored and nxt.get("kind") != "ipa_local_rollback"
              and only_on(profiles, ev["to_profile"], ev["from_profile"], ev["serving_operator"]))
    return list(DELIVERED) + ["RESULT_PENDING", "VERIFYING", "SUCCEEDED" if proven else "UNCONFIRMED"]


def _switch_problems(run: dict) -> list[str]:
    """Every gate verdict must follow from its own checks, and every executed switch must match the event log: the
    eIM record, the proposal id for that attempt, and the path the events imply."""
    out, events = [], run["events"]
    profiles = SCENARIOS[run["scenario"]]["profiles"]
    for t in run["trace"]:
        tr = t["tool_result"] if isinstance(t["tool_result"], dict) else {}
        g, at = tr.get("gate"), f"step {t['step']}"
        if not g:
            continue
        if g["failed"] != [k for k, ok in g["checks"].items() if not ok] or g["allowed"] != (not g["failed"]):
            out.append(f"{at}: gate verdict does not follow from its checks")
        if not tr.get("executed"):
            continue
        eim = tr.get("eim") or {}
        seq = eim.get("seq", 0)
        ev = events[seq - 1] if 0 < seq <= len(events) else None
        if ev != eim or ev.get("kind") != "eim_enable_profile" or not ev.get("ok"):
            out.append(f"{at}: the switch's eIM record does not match the event log")
            continue
        if not (g["target"] == tr.get("target") == ev["to_profile"] != ev["from_profile"]):
            out.append(f"{at}: approved target, tool result and enabled profile do not match")
        attempt = sum(e["kind"] == "eim_enable_profile" and bool(e.get("ok")) for e in events[:seq - 1])
        if g["proposal_id"] != f"{idempotency_key(run['scenario'], ev['from_profile'], g['target'])}.{attempt}":
            out.append(f"{at}: approved proposal id does not match this switch and attempt")
        expected = _expected_path(ev, events[seq] if seq < len(events) else {}, profiles)
        if expected is None or tr.get("transition") != expected:
            out.append(f"{at}: switch path {tr.get('transition')} does not follow from the event log")
    return out


def _view(r: dict) -> dict:
    """What a replay must reproduce exactly: every step's tool, route, result and rates, the events and the outcome.
    Recorded inputs are left out because a replay cannot re-derive them: model answers and their measured latency,
    and Bedrock's plan review."""
    steps = [{"tool": t["tool"], "status": t["tool_status"], "note": t.get("note"), "rates_after": t["rates_after"],
              "route": t["decision"] and [t["decision"][k] for k in ("selected", "route", "excluded", "eligible")],
              "result": ({k: v for k, v in t["tool_result"].items() if k != "bedrock_plan"}
                         if isinstance(t["tool_result"], dict) else t["tool_result"])} for t in r["trace"]]
    return json.loads(json.dumps({"steps": steps, "events": r["events"], "outcome": r["outcome"]}, default=str))


def _replay_problems(run: dict) -> list[str]:
    """The twin is deterministic, so the recorded Decider and human answers, fed back through the current code, must
    reproduce the recorded trace, events and outcome. Any edit the simulation would not have produced fails here."""
    try:
        inc = Incident(run["scenario"], approve=run.get("approved") is True, use_bedrock=False,
                       decider=ReplayDecider([t["decision"] for t in run["trace"]]))
        finish(inc, recorded_answers(run))
        replayed = inc.result()
    except Exception as e:  # a trace the code cannot even replay is not valid
        return [f"replay failed: {type(e).__name__}: {e}"]
    if _view(replayed) != _view(run):
        return ["replaying the recorded answers does not reproduce the recorded trace, events and outcome"]
    return []


def problems(run: dict) -> list[str]:
    out, prev_gate, allowed_gates = [], None, 0
    hidden = SCENARIOS[run["scenario"]]["hidden"]["cause"]
    trace = run["trace"]
    for i, t in enumerate(trace):
        out += step_problems(t, prev_gate, hidden)
        prev_gate = _gate(t)
        allowed_gates += bool(prev_gate and prev_gate["allowed"])
        pending = bool(prev_gate and prev_gate["failed"] == ["human_approval"])
        if (t["tool"] == TOOLS["evaluate_profile_change"] and not pending
                and not (isinstance(t["tool_result"], dict) and t["tool_result"].get("verified_restored"))
                and (i + 1 == len(trace) or trace[i + 1]["tool"] != TOOLS["escalate_or_wait"])):
            out.append(f"step {t['step']}: a profile change that did not restore service must be followed by a handoff")
    last_gate = _gate(trace[-1]) if trace else None
    if trace and not (run["outcome"]["restored"] or trace[-1]["tool"] == TOOLS["escalate_or_wait"]
                      or (last_gate and last_gate["failed"] == ["human_approval"])):
        out.append("run ends without being restored, handed off, or waiting for a human approval")
    answers = run.get("human_answers", {})
    for t in trace:
        g, note = _gate(t), t.get("note") or ""
        if g and g["allowed"] and not (run.get("approved") is True or answers.get(g["proposal_id"]) is True):
            out.append(f"step {t['step']}: gate passed without a recorded human approval of {g['proposal_id']}")
        for verb, value in (("operator approved proposal ", True), ("operator declined proposal ", False)):
            if note.startswith(verb) and answers.get(note.removeprefix(verb)) is not value:
                out.append(f"step {t['step']}: '{note}' does not match the recorded human answers")
    enables = sum(e["kind"] == "eim_enable_profile" and e.get("ok") for e in run["events"])
    if enables > allowed_gates:
        out.append(f"{enables} profile enables but only {allowed_gates} passing gates")
    out += _switch_problems(run)
    out += _replay_problems(run)
    expected = None  # the profile the events leave active, which the outcome must report
    for e in run["events"]:
        if e["kind"] in ("eim_enable_profile", "eim_rollback", "ipa_local_rollback") and e.get("ok", True):
            expected = e["to_profile"]
    if expected and run["outcome"].get("active_profile") != expected:
        out.append(f"outcome reports {run['outcome'].get('active_profile')} active but the profile events end on {expected}")
    for i, e in enumerate(run["events"]):  # a device-side rollback must undo the unreported enable just before it
        prev = run["events"][i - 1] if i else {}
        if e["kind"] == "ipa_local_rollback" and not (
                prev.get("kind") == "eim_enable_profile" and prev.get("ok") and prev.get("rollback_authorized")
                and not prev.get("result_reported")
                and (e.get("from_profile"), e.get("to_profile")) == (prev.get("to_profile"), prev.get("from_profile"))):
            out.append(f"event {e['seq']}: local rollback without an authorizing, unreported profile enable it undoes")
    o = run["outcome"]
    if o.get("forbidden_executions"):
        out.append(f"{o['forbidden_executions']} forbidden executions recorded")
    if trace and o["final_rates"] != trace[-1]["rates_after"]:
        out.append("outcome rates differ from the rates recorded after the last step")
    if o["restored"] != all(o["final_rates"][k] >= RESTORED_THRESHOLD for k in RESTORED_RATES):
        out.append("claims restored or not restored against its registration, data session and telemetry rates")
    return out


if __name__ == "__main__":
    failed = False
    for path in sys.argv[1:]:
        with open(path) as f:
            found = problems(json.load(f))
        failed |= bool(found)
        print(f"{'FAIL' if found else 'ok  '} {path}" + "".join(f"\n     - {p}" for p in found))
    sys.exit(failed)
