"""Invoke the deployed SIMShift runtime and record its trace.

    AWS_PROFILE=<admin profile> python deploy/invoke.py TRANSIENT --out docs/sample-runs/aws/TRANSIENT.json
    python deploy/invoke.py BR_PROFILE --approve-id <proposal id from the pending run> --out ...

The runtime ARN is read from the AgentCore CLI's local deployed state (gitignored). A trace is written only when
every Decider call reached the deployed Decider and Bedrock reported no error, so a fallback caused by networking is
never published as an AWS run.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid

import boto3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from patterns.capability_aware_router.router import DECIDER_MODEL  # noqa: E402
from simshift.agent import write_trace  # noqa: E402

STATE = os.path.join(os.path.dirname(__file__), "agentcore", "agentcore", ".cli", "deployed-state.json")


def runtime_arn() -> str:
    state = json.load(open(STATE))
    return state["targets"]["default"]["resources"]["runtimes"]["simshift"]["runtimeArn"]


def problems(res: dict) -> list[str]:
    out = [f"runtime error: {res['error']}"] if "error" in res else []
    for t in res.get("trace", []):
        raw = (t.get("decision") or {}).get("raw")  # None: only the fallback was admissible, so no Decider call
        if raw and (raw.get("error") or raw.get("model") != DECIDER_MODEL.split("/")[-1]):
            out.append(f"step {t['step']}: Decider not reached ({raw.get('error') or raw.get('model')})")
    if res.get("bedrock_error"):
        out.append(f"Bedrock error: {res['bedrock_error']}")
    elif "error" not in res and not res.get("report"):
        out.append("no Bedrock report")
    for t in res.get("trace", []):
        plan = (t.get("tool_result") or {}).get("bedrock_plan") if isinstance(t.get("tool_result"), dict) else None
        if isinstance(plan, dict) and plan.get("error"):
            out.append(f"step {t['step']}: Bedrock plan review failed")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario")
    ap.add_argument("--approve-id", action="append", default=[], help="a proposal id a human approved")
    ap.add_argument("--out")
    a = ap.parse_args()
    client = boto3.client("bedrock-agentcore", region_name=os.environ.get("AWS_REGION", "eu-central-1"))
    t0 = time.perf_counter()
    resp = client.invoke_agent_runtime(agentRuntimeArn=runtime_arn(), runtimeSessionId=str(uuid.uuid4()) + "-simshift",
                                       payload=json.dumps({"scenario": a.scenario, "approved_ids": a.approve_id}))
    res = json.loads(b"".join(resp["response"]))
    wall = round(time.perf_counter() - t0, 1)
    for t in res.get("trace", []):
        d = t.get("decision") or {}
        raw = d.get("raw") or {}
        print(f"step {t['step']}: {d.get('route', '-')} -> {t['tool']}  "
              f"decider {raw.get('latency_ms')} ms server / {raw.get('client_latency_ms')} ms client")
    print(f"outcome: {res.get('outcome', {}).get('restored')}  pending: {res.get('pending_approval')}  "
          f"invoke wall time {wall} s")
    bad = problems(res)
    if bad:
        print("NOT RECORDED:\n  " + "\n  ".join(bad))
        sys.exit(1)
    if a.out:
        write_trace(a.out, res)
        print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
