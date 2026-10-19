# Architecture and simulation scope

## Flow of one recovery step

```
 FleetTwin.observe()  ──►  policy.exclusions(state)  ──►  Strands Decider 2B
 (observable state only)    removes inadmissible           `choice` over the
                            options + records why          admissible options
                                                                  │
                                    confidence-aware route ◄──────┘
                                    act | gather_evidence | fallback
                                                │
                                agent.tool.<selected tool>()      (Strands direct tool call)
                                                │
                       InterventionHandler gate re-checks the same policy ── Deny if inadmissible
                                                │
              ┌─────────────── tool runs against the deterministic twin ───────────────┐
              │ retry / operator reselection / read-only diagnostics / escalate         │
              │ prepare_guarded_profile_transition:                                     │
              │   Bedrock plan review ─► hard gate + human approval ─► virtual eIM      │
              │   enable ─► verify registration AND app telemetry ─► rollback if not    │
              └─────────────────────────────────────────────────────────────────────────┘
                                                │
                       loop until restored, a terminal tool, or MAX_STEPS (then escalate)
                                                │
                              Bedrock explains the trace for a NOC engineer
```

Code: [`simshift/agent.py`](../simshift/agent.py) (`Incident`: one steppable session, the six tools, the audit),
[`simshift/policy.py`](../simshift/policy.py) (exclusions, gate, transition path, counterfactuals),
[`simshift/simulator.py`](../simshift/simulator.py) (twin and virtual eIM),
[`patterns/capability_aware_router/router.py`](../patterns/capability_aware_router/router.py) (the reusable pattern).

## Three ways to drive the same incident

`Incident.step()` runs exactly one observe → policy → Decider → gated tool cycle. Three front ends call it:

| Front end | Who loops | Used for |
|---|---|---|
| `python -m simshift.agent` | a Python `while not done` loop | the original recorded runs; `--replay` |
| `python -m simshift.orchestrator` | a Strands agent on Bedrock with two zero-argument tools, `get_incident_state` and `advance_recovery` | the "Bedrock runs the agent" mode; its report replaces the explanation |
| `python -m simshift.web` | a person pressing *Next step*, plus a real approval dialog | the Recovery Decision Inspector UI (127.0.0.1 only; it refuses requests whose Host is not local and POSTs that are not JSON from its own page, so another web page or a rebound host name cannot drive it) |

In orchestrator mode Bedrock decides when to look, when to advance and how to report. `advance_recovery` has no
parameters, so Bedrock cannot name a recovery tool, skip the policy or approve a change. If Bedrock stops early, the
incident is finished deterministically and Bedrock is asked to rewrite its report for the final trace
(`report_after_fallback` in the result). If a Bedrock call fails, the incident is still finished and the error is
recorded. The two tools share a budget of 16 calls; past it they stop the agent loop. All six orchestrated runs in
[`docs/sample-runs/orchestrated/`](sample-runs/orchestrated/) replay to the same tools through the plain loop.

## Role boundaries

| Component | Owns | Does not own |
|---|---|---|
| Strands Decider 2B | choosing the next tool among admissible options; its probabilities and derived confidence | authorization, network state, safety |
| Router (pattern) | turning a choice and its confidence into a route; calling the Strands tool | diagnosis |
| Strands agent | tool registry, tool execution, intervention hooks, message history | simulated outcomes |
| Amazon Bedrock (Claude Haiku 5.5) | reviewing profile-change plans (advisory); explaining the outcome; in orchestrator mode, running the loop and writing the report | selecting any recovery tool; authorizing any change |
| Policy / gate | hard admissibility rules, reachability, authorization, approval, idempotency | probabilistic judgment |
| Digital twin | synthetic state transitions, hidden causes, outcomes | anything real-world |

## Real vs simulated

**Real:** Decider inference (local HTTP server, pinned checkpoint), Bedrock Converse calls through Strands, Strands
tool execution and intervention hooks.

**Simulated:** every device, operator, eSIM profile, eIM/IPA command and rate. No carrier, eUICC, SM-DP+ or
GSMA SGP.32 interface is called or claimed.

## Simulation scope and simplifications

- **Cohort-level.** One incident is one cohort, for example 3,200 devices. Rates are cohort aggregates; individual devices are not simulated.
- **Two recovery mechanisms kept separate.** *Operator reselection* moves to another operator that the **active**
  profile already permits. A *profile switch* enables a different **installed** profile on the eUICC and needs a
  management path.
- **Management reachability is derived, not assumed.** A path that rides on cellular works only while the active
  profile registers. In Germany, management is cellular and registration is failing, so device diagnostics and
  profile changes are inadmissible there. Brazil's depot trackers keep a non-cellular gateway path, so a profile
  change can be delivered even though the active profile cannot register. Offline devices have no path at all.
- **Profile lifecycle.** The eSIM lifecycle is reduced to a state machine: enable, IPA acknowledgement, re-registration, verification of
  registration **and** application telemetry, and rollback if verification fails. Commands are idempotent per attempt.
  No profile download, no cryptography, no certified SGP.32 flow.
- **Deterministic.** There is no randomness; cloning a twin and replaying the same actions gives identical state and events.

## Keeping the answer away from the models

Each scenario fixture stores its true cause and best actions under `hidden`, alongside network health, ingestion
health and power state. `FleetTwin.observe()` exposes only what an operator could observe: rates, serving operator,
active profile, whether another allowed operator or an alternate profile is available, management reachability,
retry count and collected diagnostics. The Bedrock plan prompt also gets the installed profiles and their operators.
Early development probes also sent the scenario ID, which hints at the answer; it was removed from the observable state. Tests check that none of the hidden fields, cause strings or
scenario IDs appear in anything sent to Decider or Bedrock (`tests/test_agent.py::test_no_truth_leakage*`).

## Hard rules (deterministic; no model can bypass them)

A profile change is refused at the gate unless **all** of the following hold. The rules marked (*) also remove it from
Decider's options beforehand:
- the eUICC supports profile enable;
- (*) the active profile is failing registration;
- (*) no operator reselection is available on the active profile;
- (*) modem diagnostics show a registration reject cause;
- (*) the management path is reachable;
- the target profile is installed and not active, and its operator is in coverage;
- the fleet owner authorizes switching;
- a human approved.

Independently of the gate, the virtual eIM refuses an enable command whose approval does not match the proposal, and
one it cannot deliver because the management path is down. It does not repeat the gate's other checks. A test
replaces the gate with one that always passes and checks that the eIM still refuses an unapproved switch.

**A profile change that does not restore service is handed off.** If the gate blocks it for any reason other than a
pending approval, the eIM cannot deliver it, verification fails and it is rolled back, rollback itself fails, or the
tool errors, the next step escalates with a note that names how it ended. The Bedrock plan review is advisory: if it
fails, the error is recorded in place of the review and the proposal still goes to the gate.

**Approval is bound to one proposal.** The gate's `human_approval` check passes only for the proposal id
`hash(cohort, from profile, to profile).<number of switches already executed>`. An approval cannot be reused for
another target, and once the switch it approved has run (even if it was rolled back), a new attempt needs a new
approval. The CLI and the UI show that id and ask a person. The CLI's `--approve` flag pre-approves every proposal a
run makes; it exists for demos, replays and the benchmark, and there the binding only prevents reuse after execution.
This is a consistency binding inside the simulation, not authentication.

**Every attempt records its eUICC transition path**, and the code refuses any path outside this list:

| Path | When |
|---|---|
| `REQUESTED → BLOCKED` | a gate check failed; nothing is sent |
| `REQUESTED → VALIDATED → APPROVED → NOT_DELIVERED` | the eIM refused or could not reach the IPA |
| `… → SENT → ACK → ENABLED → VERIFYING → SUCCEEDED` | registration and telemetry verified |
| `… → VERIFYING → FAILED → ROLLED_BACK` (or `ROLLBACK_FAILED`) | verification failed |

Verification always comes before `SUCCEEDED`, and a blocked request never reaches `SENT`.

**Decider answers are checked before they are used.** An answer whose probabilities do not cover exactly the offered
options, do not sum to 1, whose choice is not the most probable option, or whose confidence is not
`(N·p_max − 1)/(N − 1)` goes to the fallback. Every real answer we recorded passes.

**An independent audit counts violations.** A Strands hook records, for every tool call, whether the policy excluded
that option in the state it ran in. `forbidden_executions` counts excluded tools that ran anyway, and
`blocked_calls` counts those the gate denied. Both are recomputed from the policy, so a broken gate would show up
as a non-zero count (`tests/test_agent.py::test_audit_counts_a_forbidden_execution_when_the_gate_is_missing`).

**Counterfactuals never touch the live incident.** `policy.counterfactual(twin, option)` runs one option on a
clone of the current state and reports what would have happened. Policy exclusions are shown, not enforced, so a
rejected option can be seen failing. A profile change still goes through the full gate, so the UI's "what if:
evaluate_profile_change" on OFFLINE shows `REQUESTED → BLOCKED` with `management_path_reachable` failed.

**Every published trace is validated in CI** (`python -m simshift.validate`): the executed tool must be the routed
admissible option, an `act` route must run the Decider choice, recorded answers must pass the checks above, every
profile enable needs a passing gate, and "restored" needs passing registration and telemetry rates.

Retries are bounded at 5, excluded once registration is healthy, and excluded once modem diagnostics show a reset
loop (more than 5 resets per day). Read-only diagnostics run once per incident. The loop stops after 6 steps and
escalates.

## Scenarios

| Scenario | Hidden cause | What a good run does |
|---|---|---|
| `BR_PROFILE` | the only operator on the active profile is down | diagnose, then a gated, approved profile switch |
| `OFFLINE` | devices lost power at a remote site | escalate; never send an OTA command |
| `JP_INGEST` | cloud ingestion rejects payloads | find the ingestion fault; no network or eSIM change |
| `DE_OPERATOR` | primary network down; the active profile allows a second operator | operator reselection, no eSIM change |
| `FW_LOOP` | a firmware rollout put modems in a reset loop | find the reset loop and escalate to the device team; no network or eSIM change can fix it |
| `TRANSIENT` | radio congestion after a cell site restart | one bounded retry |

## Planned AWS deployment (not deployed yet)

- Agent: Amazon Bedrock AgentCore Runtime, running the orchestrator entry point.
- Decider: the pinned `strands-decider serve` container on ECS Fargate (CPU), reachable only from the agent's
  network. The upstream server has no authentication and is meant for one request at a time, so it stays private and
  single-tenant.
- Bedrock: Claude Haiku 5.5 in eu-central-1, as today.

No latency or cost figure for this deployment exists yet; none is quoted anywhere in this repository.
