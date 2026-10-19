# Measurements (what was actually observed)

All numbers below were measured on 2026-10-18 and 2026-10-19 on synthetic incidents. The agent and Decider are not hosted on AWS
yet; only the Bedrock calls run on AWS. Not yet verified: Decider latency and memory on AWS hardware, and the
AgentCore Runtime deployment. This page will be updated once the AWS deployment exists.

## Decider inference (local)

Model `StrandsAgents/strands-decider-2B-qwen3.5-v1-2610`, repo `strands-labs/strands-decider` @ `930e6d5d`.

| Backend | Hardware | Warm `choice` latency | Peak memory |
|---|---|---|---|
| MLX (in-process) | Apple M4 Max laptop | median 401 ms (5 calls, 4 options) | 4.8 GB |
| MLX (HTTP server), first agent runs | same | 367–517 ms per decision | — |
| MLX (HTTP server), later runs | same | median 122 ms (101–145, 12 decisions in the orchestrated runs); p50 92 ms, p95 118 ms (135 decisions in the benchmark) | — |
| torch CPU (in-process) | same laptop, CPU only | about 1.0 s | 12.1 GB (fp32) |

The server's `latency_ms` field is what is reported here; the benchmark table further down reports client-side wall
clock per choice (p50 94 ms, p95 119 ms for the same 135 decisions), so that Decider and Bedrock are timed the same way. The later runs were faster on the same long-running server; it
reports `prefix_cache: true`, and the incidents share most of their prompt, which is the likely reason. We did not
isolate the cause. The first-ever load took about 450 s, almost all of it downloading the ~4.3 GB base model; a
cached load takes about 2 s. Upstream publishes about 115 ms on an RTX 3090 for an older checkpoint. We have **not**
reproduced that number on a GPU.

## Agent runs (real Decider + real Bedrock, synthetic fleet)

Traces: [`docs/sample-runs/`](sample-runs/), recorded 2026-10-18 with the first version of the agent (earlier trace
format; they still replay and validate). Bedrock model: `eu.anthropic.claude-haiku-5-5` (eu-central-1).
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

### Orchestrated runs (Bedrock runs the loop, Decider picks every tool)

Traces: [`docs/sample-runs/orchestrated/`](sample-runs/orchestrated/), recorded 2026-10-19 with
`python -m simshift.orchestrator` on the current code. In every run Bedrock called `advance_recovery` until the
incident was terminal (no deterministic finish was needed), and Decider's answers for the four original scenarios were
identical to the table above.

| Scenario | Steps (`advance_recovery` calls) | Decider choices (p, conf) → route | Outcome | Simulated minutes | Bedrock tokens in / out |
|---|---|---|---|---|---|
| BR_PROFILE | 3 | as above | restored, 1 profile change | 55 | 8,663 / 1,114 |
| DE_OPERATOR | 2 | as above | restored, no eSIM change | 20 | 5,025 / 745 |
| JP_INGEST | 3 | as above | escalated with the ingestion finding | 85 | 7,537 / 814 |
| OFFLINE | 2 | as above | escalated, no OTA command | 70 | 5,030 / 654 |
| FW_LOOP | 3 | retry_connection (0.54, 0.39) → gather_evidence: modem diagnostics; escalate_or_wait (0.62, 0.25) → gather_evidence: data-path diagnostics; only the fallback left | escalated with the reset-loop finding | 85 | 7,511 / 826 |
| TRANSIENT | 1 | retry_connection (0.84, 0.79) → act | restored by one retry | 5 | 3,171 / 528 |

Bedrock token counts are the Strands `accumulated_usage` of the orchestrating agent. The BR_PROFILE run also made one
plan-review call inside the profile-change tool, which is not included in that count.

## Benchmark

Full table: [`docs/benchmark/benchmark-2026-10-19.md`](benchmark/benchmark-2026-10-19.md), run on 2026-10-19. The
matching `.json` keeps every step's raw answer, tool result and twin event. A test re-derives each row's score from
those records, recomputes every summary number, and runs the full trace validator on all 300 runs.
Run it with `python -m simshift.benchmark --stamp <label>`.

60 generated incidents, 10 in each of 6 families (operator, profile, application, unreachable, firmware, transient),
seeds 9000–9009. Every chooser answered the same typed question through the same router, policy filter and profile
gate, so only the choice step differs. Approvals were auto-granted in this run only. An escalation counts as a correct
end for application and firmware incidents only if the diagnostic that finds the cause ran first.

| Metric | rules | random | **decider** | bedrock | bedrock+conf |
|---|---:|---:|---:|---:|---:|
| Correct end state, with the evidence | 95.0% | 51.7% | **96.7%** | 91.7% | 88.3% |
| First action acceptable | 95.0% | 46.7% | **86.7%** | 81.7% | 83.3% |
| First choice = preferred tool | 95.0% | 31.7% | 50.0% | 81.7% | 81.7% |
| Unnecessary profile changes | 0 | 0 | 0 | 0 | 0 |
| Forbidden executions (audited) | 0 | 0 | 0 | 0 | 0 |
| Mean steps | 1.93 | 2.05 | 2.58 | 1.70 | 1.72 |
| Mean simulated minutes | 52.3 | 62.6 | 54.5 | 50.8 | 53.8 |
| Chooser latency p50 / p95 | — | — | **94 / 119 ms** | 2,026 / 3,334 ms | 2,051 / 3,292 ms |
| Bedrock tokens (in / out) | 0 | 0 | **0** | 47,679 / 26,994 | 50,040 / 31,930 |

`bedrock` asks Haiku 5.5 to name one option; with no probabilities, the router always acts on it. `bedrock+conf`
asks for an option and a 0–1 confidence, turns that into the distribution with the same derived confidence, and
routes it with the same 0.5 threshold and read-only fallback as Decider.

How to read it:
- **Decider's raw first pick was the preferred tool only half the time, yet 58 of 60 incidents ended correctly.** The
  confidence routing did that. The 17 first answers at confidence ≥ 0.5 all picked the preferred tool. Of the 43
  below 0.5, 13 did; the router ran the most probable read-only check instead, and 35 of those 43 first actions were
  acceptable. The 0.5 threshold was set before this run and not tuned on it.
- **Bedrock's stated confidence did not help.** All 92 stated confidences were between 0.60 and 0.82, so the 0.5
  threshold never held an answer back, and `bedrock+conf` did slightly worse than `bedrock`.
- **Bedrock picked the preferred first tool more often** (81.7%) but did worse on transient incidents: it always
  started with modem diagnostics and then escalated instead of retrying in 4 of 10. It also escalated one application
  incident before the data-path check. 6 of its 100 answers (8 for `bedrock+conf`) were unusable, at least 5 of them
  cut off at the 512-token output limit; each went to the fallback. Token counts include the cut-off calls.
- **Decider was about 20 times faster per choice** (p50 94 ms on a laptop GPU vs 2.0 s for a Bedrock call) and used
  no Bedrock tokens. These run on different hardware, so this is not a like-for-like model comparison; it is what an
  agent built this way experiences.
- **The guardrails, not the chooser, kept every strategy safe.** No chooser made a forbidden execution or an
  unnecessary profile change. The chooser decides how fast and whether recovery happens.

Caveats, all of which apply to every number above:
- The incidents are synthetic. Each family was designed with observable signals that point to its cause, and the
  option descriptions were written by us. Treat this as a check that the pieces work together, not as field evidence.
- The seeds were never used for tuning, but the families are the same ones the six hand-written scenarios come from.
- "Rules" is a hand-written runbook written from domain knowledge, not fitted to the generator. It checks the
  recent-firmware flag before the attach trend, so it misses the 3 transient incidents where that flag is set as a
  distractor.
- One run per chooser; no confidence intervals.

## Known Decider misses and what we changed

- **Brazil, steps 1–2.** The top choice was `retry_connection`, which cannot help on a dead operator. Its confidence was
  low, so the router ran read-only diagnostics instead.
- **Japan, early version.** After the ingestion finding, the model preferred a profile change. A deterministic rule now
  excludes profile changes while the active profile registers normally.
- **Firmware loop, development run.** After modem diagnostics reported a reset loop, Decider still preferred
  `retry_connection` (p 0.75, confidence 0.50, twice), so two retries ran before it escalated. That run was not saved.
  A deterministic rule now excludes retries once a reset loop is diagnosed; the recorded FW_LOOP run above is after
  that change.
- **Firmware loop, benchmark.** On 2 of the 10 generated firmware incidents, Decider chose `retry_connection` at all
  six steps: the first, at low confidence, was routed to the read-only data-path check, the next five ran as retries,
  and the step limit then escalated. The reset-loop rule never fired
  because modem diagnostics never ran, so these count as escalations without the evidence. Not fixed: requiring modem
  diagnostics before retrying would be a rule written for this result.
- **Option descriptions.** Adding *when each tool suits* to the descriptions moved the top choice to the expected
  option in more of our dev scenarios. These are the hand-written scenarios, so this is tuning, not a held-out result.
- **Earlier probes were contaminated.** Before the fix (observable state only; see
  [architecture.md](architecture.md#keeping-the-answer-away-from-the-models)), our first probes sent the scenario ID,
  which hints at the answer. All numbers on this page come from runs after that fix.
