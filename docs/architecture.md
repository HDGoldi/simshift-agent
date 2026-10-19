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
              │   enable ─► result reported? ─► verify registration, data session AND  │
              │   app telemetry ─► rollback if not (never after a missing result)       │
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
When the budget runs out, Bedrock's report is discarded and the result says why; a report is never returned for an
incident state it did not see. The report is Bedrock's prose and is not checked against the trace; the trace and
`outcome` in the same result are the record.

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

What is modelled, what is simplified and what is left out, in telecom terms, is listed in
[telecom-fidelity.md](telecom-fidelity.md). The short version:

- **Cohort-level.** One incident is one cohort, for example 3,200 devices, assumed to be pre-segmented: same
  symptoms, firmware, eUICC capability and owner policy. Rates are cohort aggregates, and a profile switch is applied
  to the whole cohort in one step. Per-device eligibility, canaries and staged rollout are not simulated, even when
  Bedrock's plan review suggests them.
- **Retry and reselection are carrier-side.** Neither stands for a modem command, which is why both work without a
  management path. A retry stands for the network forcing a fresh attach. Reselection stands for steering: the failing
  network is barred for the subscription, and the devices' own automatic network selection moves to the next operator
  the active profile allows. No AT commands are modelled.
- **Two recovery mechanisms kept separate.** *Operator reselection* moves to another operator that the **active**
  profile already permits. A *profile switch* enables a different **installed** profile on the eUICC and needs a
  management path.
- **Management reachability is derived, not assumed.** A path that rides on cellular works only while the active
  profile registers. In Germany, management is cellular and registration is failing, so device diagnostics and
  profile changes are inadmissible there. Brazil's depot trackers keep a non-cellular gateway path, so a profile
  change can be delivered even though the active profile cannot register. Offline devices have no path at all.
- **Profile lifecycle.** The eSIM lifecycle is reduced to a few milestones: the package is delivered to the IPA, the
  eUICC result is reported back to the eIM (only if a management path still works after the switch), and then
  registration, data session **and** application telemetry are verified. Delivery and execution are one simulated
  step. A failed verification is rolled back by the eIM re-enabling the previous profile, which the original approval
  covers. If the new profile cannot connect and the result cannot be reported, the device rolls back on its own (this
  stands in for SGP.32's IPA-triggered rollback). The virtual eIM requires a string target naming an installed,
  inactive profile before it attempts delivery. Exact duplicate commands are served from the approval-keyed cache
  first—even when the successful target is now active—so they return the original result without another event or
  state change. New invalid-target and other command-not-sent refusals remain uncached audit events; under the
  simulation's existing event accounting, each `eim_enable_profile` refusal still represents 30 simulated minutes.
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
- the eUICC supports profile enable, and rollback, so a failed switch can be undone;
- (*) the active profile is failing registration;
- (*) no operator reselection is available on the active profile;
- (*) modem diagnostics show a registration reject cause;
- (*) the management path is reachable;
- the target profile is installed and not active, and its operator is in coverage;
- the fleet owner authorizes switching;
- a human approved.

Independently of the gate, the virtual eIM serves an exact cached command duplicate before revalidating its target.
For an uncached command, it rejects a non-string target and refuses a target that is not an installed profile or is
already active before checking the proposal, capability, owner authorization, or reachability. It also refuses an
enable command whose approval does not match the proposal, one for an eUICC that cannot enable profiles or a fleet
whose owner forbids switching, and one it cannot deliver because the management path is down. It does not repeat the
gate's evidence checks (reject cause, reselection, coverage). A test replaces the gate with one that always passes and
checks that the eIM still refuses an unapproved switch.

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

**Every attempt records its profile-switch path.** These are SIMShift's own workflow states, loosely following
SGP.32 milestones; they are not SGP.32 state names. The code refuses any path outside this list:

| Path | Phase | When |
|---|---|---|
| `REQUESTED → BLOCKED` | prepare | a gate check failed; nothing is sent |
| `REQUESTED → VALIDATED → AWAITING_APPROVAL` | prepare | every check passed except the human approval; nothing is sent yet |
| `… → APPROVED → NOT_DELIVERED` | deliver | the eIM refused or could not reach the IPA |
| `… → APPROVED → DELIVERED → RESULT_REPORTED → VERIFYING → SUCCEEDED` | deliver, execute, verify | the eUICC result arrived, then registration, data session and telemetry were verified |
| `… → RESULT_REPORTED → VERIFYING → FAILED → ROLLED_BACK` (or `ROLLBACK_FAILED`) | verify | verification failed; the eIM re-enables the previous profile |
| `… → DELIVERED → RESULT_PENDING → VERIFYING → SUCCEEDED` | verify | no result reached the eIM, but the network shows the devices registered on an operator only the target profile allows, and service is restored |
| `… → DELIVERED → RESULT_PENDING → VERIFYING → UNCONFIRMED` | verify | no result and no working service: the state is unknown to the eIM, so no second command is sent and a human reconciles |

Verification always comes before `SUCCEEDED`, a blocked request is never `DELIVERED`, and a missing result is never
read as success.

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

**Every published trace is validated in CI** (`python -m simshift.validate`). The twin is deterministic, so the
validator first replays the recorded Decider and human answers through the current code. The replay must reproduce
the recorded steps, events and outcome exactly. The same check runs on all 300 benchmark rows. Some recorded values
are inputs that a replay cannot re-derive, so they are not verified this way: Decider's answers with their model
name and measured latency, and Bedrock's plan reviews, explanations and reports. For the benchmark, a test checks
each Decider timing against the server's own latency for the same call. On top of that, the executed tool must be the routed
admissible option, an `act` route must run the Decider choice, recorded answers must pass the checks above, every
profile enable needs a passing gate, every passing gate needs a recorded human approval (or the scripted
pre-approval), approve and decline steps must match the recorded answers, a device-side rollback must undo an
authorized enable that reported no result, each switch path must agree with the eIM result it reports on, an
unreported switch marked `SUCCEEDED` needs registration on an operator only the target profile reaches, the outcome's
active profile must be where the profile events leave it, and "restored" needs passing registration, data session and
telemetry rates.

## Actions

| Option | Stands for | Executor | Needs the management path | Changes state | Evidence it produces |
|---|---|---|---|---|---|
| `retry_connection` | the network forces a fresh attach, with back-off | carrier | no | retry counter; clears short congestion | rates after the attempt |
| `try_allowed_operator` | steering to another operator the active profile allows | carrier; device's automatic selection follows | no | serving operator, same profile | rates after the move |
| `investigate_device` | pull modem and firmware diagnostics | device agent | yes | none (read-only) | reject cause, resets per day, firmware comparison |
| `investigate_data_path` | network-side session, APN and ingestion checks | network and backend | no | none (read-only) | data sessions, APN, ingestion errors, attach attempts seen |
| `evaluate_profile_change` | propose a switch to an installed profile; runs only after a bound human approval | backend, then eIM to IPA | yes | enabled profile, reversible | the profile-switch path above |
| `escalate_or_wait` | hand off with the collected evidence | human | no | none | the handoff record |

## Stop conditions

- **Restored:** registration, data session and application ACK all at 95% or more.
- **Escalation:** the fallback ran, or a profile change ended in anything but `SUCCEEDED`.
- **Waiting:** a proposal is waiting for a human.
- **Retries** are bounded at 5 and excluded in four states:
  - registration is already healthy;
  - modem diagnostics show a reset loop (more than 5 resets per day);
  - modem diagnostics show a registration reject from the serving network, so the same reject and network back-off
    would follow;
  - the network has seen no attach attempts at all, so there is nothing for a network-side retry to reach.
- **Read-only diagnostics** run once per incident.
- **Step limit:** the loop stops after 6 steps and escalates.

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
