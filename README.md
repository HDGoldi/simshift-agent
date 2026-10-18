# SIMShift: When Not to Switch

**When IoT devices lose connectivity, the wrong recovery action can be worse than doing nothing.**

SIMShift is an IoT connectivity recovery agent. At every step, **Strands Decider 2B** chooses the next investigation
or recovery tool. **Strands Agents** executes exactly that tool, and **Amazon Bedrock** reviews profile-change plans
and explains the outcome. The agent works on a deterministic digital twin of a cellular IoT fleet with virtual eSIM
profiles. A hard policy decides what is admissible, so no model can switch a profile on its own authority.

`#strands-decider-2b` `#tool-selection` · Submission for the AWS Builder Center *Agent Experience Hackathon: Strands Decider*

> **Simulation disclosure.** The fleet, operators, eSIM profiles, eIM/IPA and every number in device state are
> synthetic. No carrier, eUICC, SM-DP+ or GSMA SGP.32 operation is performed or claimed. The Decider and Bedrock
> calls are real.

## Reusable Decider decision pattern

**[`patterns/capability_aware_router/`](patterns/capability_aware_router/README.md)** is the reusable recipe:
**CapabilityAwareRouter**, a tool-selection pattern with no telecom code. Its README covers the typed question format,
the routing rule, the wiring and usage, and it ships with its own tests and a non-telecom example. The core is one
file, [`router.py`](patterns/capability_aware_router/router.py).

```
state ─► policy removes inadmissible options (with reasons) ─► Decider `choice` over the rest
      ─► confidence ≥ 0.5: act │ else: most probable read-only tool │ else: fallback
      ─► agent.tool.<selected>()  ─► same policy re-checked by a Strands InterventionHandler
```

## The decision Decider makes

SIMShift's typed question, asked at every step ([`simshift/agent.py`](simshift/agent.py)):

> *Given the cellular connectivity symptoms, diagnostic evidence so far, and only these admissible tools, which next
> tool is most useful for safely advancing service restoration? Do not assume an unverified recovery path works.*

The option set has six options, each mapped 1:1 to a registered Strands tool (descriptions in [`simshift/policy.py`](simshift/policy.py)):

| Option | Strands tool | Kind |
|---|---|---|
| `retry_connection` | `simulate_retry_with_backoff` | bounded, network-side |
| `try_allowed_operator` | `simulate_operator_reselection` | another operator **on the active profile** |
| `investigate_device` | `query_firmware_modem_diagnostics` | read-only |
| `investigate_data_path` | `query_apn_session_app_diagnostics` | read-only |
| `evaluate_profile_change` | `prepare_guarded_profile_transition` | advisory Bedrock plan review, then hard gate + human approval, then virtual eIM |
| `escalate_or_wait` | `defer_or_escalate` | fallback |

Before Decider sees the options, the policy removes inadmissible ones. A profile change is never offered:
- while another operator on the active profile is available;
- without a management path to the device;
- while the active profile registers normally;
- before modem diagnostics show a registration reject cause.

The same rules run again at the gate, together with owner authorization and human approval. Details:
[docs/architecture.md](docs/architecture.md).

## Observed runs (real Decider + Bedrock, synthetic fleet)

| Scenario | What the agent did | Outcome |
|---|---|---|
| `BR_PROFILE` | Decider leans to `retry_connection` at conf 0.04, then 0.20, so the router runs the most probable read-only diagnostics instead. Modem shows reject #17. Decider picks `evaluate_profile_change` (conf 0.81). Bedrock review recommends proceeding as a staged change (advisory; the gate does not read it), gate + approval pass, virtual eIM enables profile_B | registration **and** app telemetry restored |
| `OFFLINE` | device diagnostics and profile change excluded (no management path), reselection excluded (no allowed operator in coverage) → network-side check (conf 0.06, read-only) → escalate (conf 0.31, fallback) | no OTA change attempted |
| `JP_INGEST` | retry and profile change excluded (registration healthy), reselection excluded (no allowed operator in coverage) → Decider picks `investigate_data_path` (conf 0.71) → ingestion regression found → modem check (conf 0.09, read-only) → escalate (only option left, no model call) | no network change; root cause handed off |
| `DE_OPERATOR` | management rides on the failing cellular link, so device diagnostics and profile change are excluded → Decider leans to `try_allowed_operator` at conf 0.47, so the router runs the read-only network-side check → Decider picks `try_allowed_operator` (conf 0.62) | recovered without touching the eSIM |

These are single runs on 2026-10-18, not a benchmark. Full traces are in [docs/sample-runs/](docs/sample-runs/).
Per-step numbers, latencies and the known Decider misses are in [docs/measurements.md](docs/measurements.md).

## Run it

```bash
# 1. Decider server (pinned: strands-labs/strands-decider @ 930e6d5d)
git clone https://github.com/strands-labs/strands-decider && cd strands-decider && git checkout 930e6d5d
uv venv && uv pip install -e ".[mlx]"        # Apple silicon; elsewhere: uv pip install -e . and use --device cpu
.venv/bin/strands-decider serve StrandsAgents/strands-decider-2B-qwen3.5-v1-2610 --device mlx --port 8099

# 2. Agent: second terminal (the server stays in the foreground). Needs AWS credentials with Bedrock access.
git clone https://github.com/HDGoldi/simshift-agent && cd simshift-agent
uv venv && uv pip install -e . pytest
AWS_PROFILE=<your-profile> .venv/bin/python -m simshift.agent BR_PROFILE --approve --out runs/br.json
.venv/bin/python -m simshift.agent OFFLINE --no-bedrock
```

Settings: `DECIDER_URL` (default `http://127.0.0.1:8099`), `SIMSHIFT_BEDROCK_MODEL` (default
`eu.anthropic.claude-haiku-5-5`), `AWS_REGION` (default `eu-central-1`). `--approve` is the human operator's
pre-approval for a profile switch. Without it, the gate stops at `human_approval`.

## Tests

`.venv/bin/pytest -q` runs 27 tests. They need no AWS credentials, and the real-Decider test skips when no server
is running. The acceptance properties covered:
- Decider's choice controls which Strands tool runs.
- Excluded options are never offered and are denied on any call path.
- Unreachable devices never get an OTA change.
- A profile change needs approval.
- Brazil restores both registration and telemetry.
- No hidden truth reaches Decider or Bedrock prompts.
- The twin is deterministic: replaying the same actions gives identical state and events.
- The step limit escalates.
- A Decider outage fails closed.

## Repository layout

```
patterns/capability_aware_router/   reusable Decider pattern (router, README, example, tests)
simshift/agent.py                   Strands agent: loop, tools, Bedrock plan + explanation, CLI
simshift/policy.py                  option descriptions, exclusions, profile-transition gate
simshift/simulator.py               deterministic fleet twin + virtual eIM/IPA/eUICC, 4 scenarios
tests/                              agent, twin and policy tests
docs/                               architecture, measurements, submission checklist, sample traces
spikes/decider_spike.py             standalone Decider API probe used to validate the API
```

## Status and next steps

Done: a working vertical slice, run locally (Decider on MLX, Bedrock in eu-central-1).

Next:
- AWS hosting: agent on Bedrock AgentCore Runtime, Decider on an ECS Fargate CPU container.
- A decision-trace UI.
- Firmware-loop and transient-disruption scenarios.
- Rules-only vs Bedrock-only vs Decider+Bedrock comparison on held-out cases.

Submission status: [docs/hackathon-submission.md](docs/hackathon-submission.md).

## License

[Apache-2.0](LICENSE). The code uses, but does not redistribute, Strands Decider (Apache-2.0), its Qwen3.5-2B base
model (Apache-2.0) and Strands Agents (Apache-2.0). Amazon Bedrock models are subject to their own service terms.
