# Measurements (what was actually observed)

All numbers below were measured on 2026-10-18. They are single runs or small samples, **not a benchmark**.
The agent and Decider are not hosted on AWS yet; only the Bedrock calls run on AWS. Not yet verified: Decider latency
and memory on AWS hardware, and the AgentCore Runtime deployment. This page will be updated once the AWS deployment
exists.

## Decider inference (local)

Model `StrandsAgents/strands-decider-2B-qwen3.5-v1-2610`, repo `strands-labs/strands-decider` @ `930e6d5d`.

| Backend | Hardware | Warm `choice` latency | Peak memory |
|---|---|---|---|
| MLX (in-process) | Apple M4 Max laptop | median 401 ms (5 calls, 4 options) | 4.8 GB |
| MLX (HTTP server) | same | 367–517 ms per decision in the agent runs below | — |
| torch CPU (in-process) | same laptop, CPU only | about 1.0 s | 12.1 GB (fp32) |

The first-ever load took about 450 s, almost all of it downloading the ~4.3 GB base model; a cached load takes about 2 s.
Upstream publishes about 115 ms on an RTX 3090 for an older checkpoint. We have **not** reproduced that number.

## Agent runs (real Decider + real Bedrock, synthetic fleet)

Traces: [`docs/sample-runs/`](sample-runs/). Bedrock model: `eu.anthropic.claude-haiku-5-5` (eu-central-1).
Act threshold: confidence ≥ 0.5.

| Scenario | Step | Options offered | Decider top choice (p, conf) | Route → tool run | Result |
|---|---|---|---|---|---|
| BR_PROFILE | 1 | 4 | retry_connection (0.28, 0.04) | gather_evidence → data-path diagnostics | |
| | 2 | 3 | retry_connection (0.47, 0.20) | gather_evidence → modem diagnostics | reject #17 found |
| | 3 | 3 | evaluate_profile_change (0.87, 0.81) | act → guarded profile transition | **restored** (Bedrock review: proceed, staged) |
| DE_OPERATOR | 1 | 4 | try_allowed_operator (0.60, 0.47) | gather_evidence → data-path diagnostics | |
| | 2 | 3 | try_allowed_operator (0.75, 0.62) | act → operator reselection | **restored**, no eSIM change |
| JP_INGEST | 1 | 3 | investigate_data_path (0.81, 0.71) | act → data-path diagnostics | ingestion regression found |
| | 2 | 2 | escalate_or_wait (0.54, 0.09) | gather_evidence → modem diagnostics | modem healthy |
| | 3 | 1 | — (no model call) | fallback → escalate | handed off, no network change |
| OFFLINE | 1 | 3 | investigate_data_path (0.37, 0.06) | gather_evidence → data-path diagnostics | no attach attempts at all |
| | 2 | 2 | escalate_or_wait (0.66, 0.31) | fallback → escalate | no OTA change attempted |

`conf` is Decider's derived confidence `(N·p_max − 1)/(N − 1)`, not a calibrated probability of being correct.

## Known Decider misses and what we changed

- **Brazil, steps 1–2.** The top choice was `retry_connection`, which cannot help on a dead operator. Its confidence was
  low, so the router ran read-only diagnostics instead.
- **Japan, early version.** After the ingestion finding, the model preferred a profile change. A deterministic rule now
  excludes profile changes while the active profile registers normally.
- **Option descriptions.** Adding *when each tool suits* to the descriptions moved the top choice to the expected
  option in more of our dev scenarios. These are the same 4 scenarios shown here, so this is tuning, not a held-out result.
- **Earlier probes were contaminated.** Before the fix (observable state only; see
  [architecture.md](architecture.md#keeping-the-answer-away-from-the-models)), our first probes sent the scenario ID,
  which hints at the answer. All numbers on this page come from runs after that fix.
