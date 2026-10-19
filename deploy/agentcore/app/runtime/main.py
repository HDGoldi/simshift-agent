"""SIMShift on Bedrock AgentCore Runtime: one invocation runs one orchestrated incident and returns its trace.

Payload: {"scenario": "BR_PROFILE", "approved_ids": ["<proposal id>"]}. A run that stops for a human returns its
`pending_approval` id; re-invoking with that id approves exactly that proposal (the twin is deterministic).
`make agentcore-bundle` copies the simshift and patterns packages next to this file before a deploy.
"""
import os

from bedrock_agentcore.runtime import BedrockAgentCoreApp

from patterns.capability_aware_router.router import DeciderClient
from simshift.orchestrator import orchestrate
from simshift.simulator import SCENARIOS

app = BedrockAgentCoreApp()


@app.entrypoint
def invoke(payload, context):
    if not isinstance(payload, dict) or not isinstance(payload.get("scenario"), str):
        return {"error": 'payload must be {"scenario": <name>, "approved_ids": [<proposal id>, ...]}'}
    scenario, approved = payload["scenario"], payload.get("approved_ids", [])
    if scenario not in SCENARIOS:
        return {"error": f"unknown scenario; choose one of {sorted(SCENARIOS)}"}
    if not isinstance(approved, list) or not all(isinstance(p, str) for p in approved):
        return {"error": "approved_ids must be a list of proposal id strings"}
    url = os.environ["DECIDER_URL"]
    res = orchestrate(scenario, decider=DeciderClient(url), approved_ids=approved)
    res["decider_source"] = f"live {url} (ECS Fargate)"
    return res


if __name__ == "__main__":
    app.run()
