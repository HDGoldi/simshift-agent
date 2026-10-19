# Measurements (what was actually observed)

All numbers below were measured on 2026-10-18 and 2026-10-19 on synthetic incidents; every run and benchmark figure
is from 2026-10-19, on the current code. The AWS section is the deployed system; the sections after it are the local
runs (Decider on a laptop GPU, Bedrock on AWS) that the benchmark also uses.

## Deployed on AWS (eu-central-1)

The orchestrator runs on Bedrock AgentCore Runtime (VPC mode, arm64) and calls Decider on a private ECS Fargate task
(arm64, 4 vCPU, 16 GB, torch on CPU, the same pinned checkpoint). Setup and network rules:
[architecture](architecture.md#aws-deployment). Traces: [`docs/sample-runs/aws/`](sample-runs/aws/), recorded
2026-10-19 with `deploy/invoke.py`, which refuses to save a run if any Decider call failed or Bedrock reported an
error. Brazil was recorded twice: the first call stopped at the approval gate, and the second call carried the
approved proposal id (`approved_ids`), so the trace records the approval as a separate human answer.

| Run | Decider top choice and confidence → route, tool (server latency) | Outcome | Bedrock tokens in / out |
|---|---|---|---|
| [BR_PROFILE.pending](sample-runs/aws/BR_PROFILE.pending.json) | retry_connection 0.04 → gather_evidence, data-path diagnostics (6.7 s); retry_connection 0.19 → gather_evidence, modem diagnostics (6.9 s); evaluate_profile_change 0.88 → act, guarded profile switch (8.0 s) | pending approval | 8,596 / 1,412 |
| [BR_PROFILE](sample-runs/aws/BR_PROFILE.json) | the same three answers (6.6 s, 6.7 s, 7.9 s); then the operator's approval re-submits the switch | **restored** | 14,674 / 1,979 |
| [DE_OPERATOR](sample-runs/aws/DE_OPERATOR.json) | try_allowed_operator 0.46 → gather_evidence, data-path diagnostics (6.8 s); try_allowed_operator 0.63 → act, operator reselection (7.0 s) | **restored** | 5,135 / 722 |
| [JP_INGEST](sample-runs/aws/JP_INGEST.json) | investigate_data_path 0.71 → act, data-path diagnostics (6.2 s); escalate_or_wait 0.08 → gather_evidence, modem diagnostics (7.0 s); only the fallback left, no model call | handed off | 7,660 / 732 |
| [OFFLINE](sample-runs/aws/OFFLINE.json) | escalate_or_wait 0.07 → gather_evidence, data-path diagnostics (6.4 s); only the fallback left, no model call | handed off | 5,275 / 653 |
| [FW_LOOP](sample-runs/aws/FW_LOOP.json) | retry_connection 0.38 → gather_evidence, modem diagnostics (6.8 s); escalate_or_wait 0.28 → gather_evidence, data-path diagnostics (7.9 s); only the fallback left, no model call | handed off | 7,821 / 786 |
| [TRANSIENT](sample-runs/aws/TRANSIENT.json) | retry_connection 0.79 → act, bounded retry (6.9 s) | **restored** | 3,254 / 560 |

- **Decider latency on Fargate CPU:** median 6.8 s per choice (6.2 to 7.9 s, server `latency_ms`, 11 calls: one run
  per scenario, Brazil's approved run; the pending run's three calls, up to 8.0 s, are not counted; client-side
  median 6.8 s). That is about 55 times the laptop GPU's 124 ms and about three times Bedrock's 2.1 s per choice in
  the benchmark. Fargate has no GPU; we did not try a GPU host.
- **Same decisions as the local runs:** every route and every tool that ran matches the local orchestrated runs in
  all six scenarios (Brazil adds the separate approval step). Decider's top choice matched in 10 of 11 calls and
  confidences differ by at most 0.013 (fp32 on CPU versus MLX). The one different top choice, OFFLINE step 1, was
  below the act threshold in both runs (0.07 and 0.06), so both ran the same read-only tool.
- **Cold start, measured once from the ECS task timestamps:** the 4.1 GB image (compressed) pulled in 67 s and the
  task reported healthy about 2.7 minutes after the scale-up. Decider is scaled to zero between sessions.
- **Memory:** about 9.2 GB in a local `docker run` of the same image with a 16 GB limit; we did not read the Fargate
  task's memory.
- The Bedrock token counts are per run and include the report; Brazil's approved run also rewrites the report after
  the approval. As in the local runs, the plan-review call inside the profile-change tool is not included.
- **The two Brazil plan reviews disagreed.** In the pending run Bedrock's review recommended proceeding. The approved
  run re-ran the incident and wrote a new review, which did not recommend proceeding and asked for a staged canary
  first; both said a blind fleet-wide switch was not advisable. The human approved after reading the first review.
  The review is advisory: the gate does not read it, and the approval is bound to the proposal id, not to a review.

## Decider inference (local)

Model `StrandsAgents/strands-decider-2B-qwen3.5-v1-2610`, repo `strands-labs/strands-decider` @ `930e6d5d`.

| Backend | Hardware | Warm `choice` latency | Peak memory |
|---|---|---|---|
| MLX (in-process) | Apple M4 Max laptop | median 401 ms (5 calls, 4 options) | 4.8 GB |
| MLX (HTTP server), first agent runs | same | 367–517 ms per decision | — |
| MLX (HTTP server), later runs | same | median 118 ms (91–125, 11 decisions in the plain-loop runs), median 124 ms (101–131, 11 decisions in the orchestrated runs); benchmark: see below | — |
| torch CPU (in-process) | same laptop, CPU only | about 1.0 s | 12.1 GB (fp32) |

The server's `latency_ms` field is what is reported here (in the benchmark: p50 105 ms, p95 122 ms over 125
decisions). The benchmark table further down reports client-side wall clock per choice (p50 106 ms, p95 123 ms for
the same decisions), so that Decider and Bedrock are timed the same way. The later runs were faster on the same long-running server; it
reports `prefix_cache: true`, and the incidents share most of their prompt, which is the likely reason. We did not
isolate the cause. The first-ever load took about 450 s, almost all of it downloading the ~4.3 GB base model; a
cached load takes about 2 s. Upstream publishes about 115 ms on an RTX 3090 for an older checkpoint. We have **not**
reproduced that number on a GPU.

## Agent runs (real Decider + real Bedrock, synthetic fleet)

Traces: [`docs/sample-runs/`](sample-runs/), recorded 2026-10-19 with `python -m simshift.agent <S> --approve` (the
plain Python loop; `--approve` is the scripted pre-approval). Bedrock model: `eu.anthropic.claude-haiku-5-5`
(eu-central-1). Act threshold: confidence ≥ 0.5.

| Scenario | Step | Options offered | Decider top choice (p, conf) | Route → tool run | Result |
|---|---|---|---|---|---|
| BR_PROFILE | 1 | 4 | retry_connection (0.28, 0.04) | gather_evidence → data-path diagnostics | |
| | 2 | 3 | retry_connection (0.47, 0.20) | gather_evidence → modem diagnostics | reject #17 found; retry now excluded |
| | 3 | 2 | evaluate_profile_change (0.94, 0.88) | act → guarded profile switch | **restored** (Bedrock review: proceed, advisory) |
| DE_OPERATOR | 1 | 4 | try_allowed_operator (0.60, 0.47) | gather_evidence → data-path diagnostics | |
| | 2 | 3 | try_allowed_operator (0.75, 0.62) | act → operator reselection | **restored**, no eSIM change |
| JP_INGEST | 1 | 3 | investigate_data_path (0.81, 0.71) | act → data-path diagnostics | ingestion regression found |
| | 2 | 2 | escalate_or_wait (0.54, 0.09) | gather_evidence → modem diagnostics | modem healthy |
| | 3 | 1 | no model call | fallback → escalate | handed off, no network change |
| OFFLINE | 1 | 3 | investigate_data_path (0.37, 0.06) | gather_evidence → data-path diagnostics | no attach attempts and no periodic updates; retry now excluded |
| | 2 | 1 | no model call | fallback → escalate | no OTA change attempted |
| FW_LOOP | 1 | 4 | retry_connection (0.54, 0.39) | gather_evidence → modem diagnostics | reset loop on the new firmware; older firmware stable on the same cells |
| | 2 | 2 | escalate_or_wait (0.65, 0.29) | gather_evidence → data-path diagnostics | sessions flapping, APN and ingestion healthy |
| | 3 | 1 | no model call | fallback → escalate | handed to the device team |
| TRANSIENT | 1 | 4 | retry_connection (0.84, 0.79) | act → bounded retry | **restored** |

`conf` is Decider's derived confidence `(N·p_max − 1)/(N − 1)`, not a calibrated probability of being correct. With
two options offered, the same p gives a higher confidence than with three, which is why Brazil's step 3 rose from
0.81 (three options, before the reject rule) to 0.88.

### Orchestrated runs (Bedrock runs the loop, Decider picks every tool)

Traces: [`docs/sample-runs/orchestrated/`](sample-runs/orchestrated/), recorded 2026-10-19 with
`python -m simshift.orchestrator <S> --approve`. In every run Bedrock called `advance_recovery` until the incident
was terminal, so no deterministic finish was needed. Decider's answers were identical to the plain-loop runs above
in all six scenarios.

| Scenario | `advance_recovery` calls | Outcome | Simulated minutes | Bedrock tokens in / out |
|---|---|---|---|---|
| BR_PROFILE | 3 | restored, 1 profile change | 55 | 8,858 / 1,096 |
| DE_OPERATOR | 2 | restored, no eSIM change | 20 | 5,134 / 700 |
| JP_INGEST | 3 | escalated with the ingestion finding | 85 | 7,666 / 684 |
| OFFLINE | 2 | escalated, no OTA command | 70 | 5,277 / 849 |
| FW_LOOP | 3 | escalated with the reset-loop finding | 85 | 7,824 / 818 |
| TRANSIENT | 1 | restored by one retry | 5 | 3,467 / 669 |

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
| Correct end state, with the evidence | 95.0% | 50.0% | **96.7%** | 91.7% | 93.3% |
| First action acceptable | 95.0% | 41.7% | **86.7%** | 83.3% | 81.7% |
| First choice = preferred tool | 95.0% | 28.3% | 50.0% | 81.7% | 81.7% |
| Unnecessary profile changes | 0 | 0 | 0 | 0 | 0 |
| Forbidden executions (audited) | 0 | 0 | 0 | 0 | 0 |
| Mean steps | 1.93 | 1.98 | 2.58 | 1.72 | 1.73 |
| Mean simulated minutes | 52.3 | 61.5 | 54.5 | 52.0 | 51.2 |
| Chooser latency p50 / p95 | — | — | **106 / 123 ms** | 2,086 / 3,431 ms | 2,043 / 3,050 ms |
| Bedrock tokens (in / out) | 0 | 0 | **0** | 47,067 / 26,261 | 50,423 / 31,181 |

`bedrock` asks Haiku 5.5 to name one option; with no probabilities, the router always acts on it. `bedrock+conf`
asks for an option and a 0–1 confidence, turns that into the distribution with the same derived confidence, and
routes it with the same 0.5 threshold and read-only fallback as Decider.

How to read it:
- **Decider's raw first pick was the preferred tool only half the time, yet 58 of 60 incidents ended correctly.**
  The confidence routing did that.
  - The 17 first answers at confidence ≥ 0.5 all picked the preferred tool.
  - Of the 43 below 0.5, 13 did. The router ran the most probable read-only check instead, and 35 of those 43 first
    actions were acceptable.
  - The 0.5 threshold was set before this run and not tuned on it.
- **Bedrock's stated confidence did not separate good answers from bad.** All 98 stated confidences were between 0.55
  and 0.85, so the 0.5 threshold never held an answer back. `bedrock+conf` ended one incident more correctly than
  `bedrock`. One run per chooser cannot tell that apart from noise.
- **Bedrock picked the preferred first tool more often** (81.7%) but did worse on transient incidents.
  - It nearly always started with modem diagnostics and then escalated instead of retrying: 5 of 10 for `bedrock`,
    4 of 10 for `bedrock+conf`.
  - 4 of its 99 answers (3 of 101 for `bedrock+conf`) were cut off at the 512-token output limit; each went to the
    fallback. Token counts include the cut-off calls.
- **Decider was about 20 times faster per choice** (p50 106 ms on a laptop GPU vs 2.1 s for a Bedrock call) and used
  no Bedrock tokens. These run on different hardware, so this is not a like-for-like model comparison; it is what an
  agent built this way experiences.
- **The guardrails, not the chooser, kept every strategy safe.** No chooser made a forbidden execution or an
  unnecessary profile change. The chooser decides how fast and whether recovery happens.
- **Compared with the earlier run on the previous code** (before the retry exclusions after a reject and for silent
  devices), Decider and rules scored the same. Random dropped from 51.7% to 50.0%, and `bedrock+conf` rose from 88.3%
  to 93.3%. Bedrock answers vary between runs, so a single run cannot attribute that rise to the rule change.

Caveats, all of which apply to every number above:
- **Synthetic incidents.** Each family was designed with observable signals that point to its cause, and we wrote the
  option descriptions. Treat this as a check that the pieces work together, not as field evidence.
- **Seeds versus families.** The seeds were never used for tuning, but the families are the same ones the six
  hand-written scenarios come from.
- **The rules baseline.** "Rules" is a hand-written runbook written from domain knowledge, not fitted to the
  generator. It checks the recent-firmware flag before the attach trend, so it misses the 3 transient incidents where
  that flag is set as a distractor.
- **One run per chooser;** no confidence intervals.

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
