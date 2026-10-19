# SIMShift: teaching an IoT recovery agent when not to switch eSIM profiles

`#strands-decider-2b` `#tool-selection`

**TL;DR**
- SIMShift is a recovery agent for cellular IoT fleets, built with Strands Agents, Strands Decider 2B and Amazon Bedrock.
- Decider 2B owns one decision: at every step it picks which diagnostic or recovery tool runs next, from options a
  deterministic policy has already filtered.
- Bedrock can run the whole agent loop, but it gets two tools without parameters, so it cannot pick a recovery tool
  or approve anything.
- On 60 generated incidents, Decider through our router ended 96.7% correctly at a median of 106 ms per choice.
  Bedrock choosing alone ended 91.7% correctly at 2.1 s per choice. The incidents are synthetic; the caveats are below.
- The reusable part is `CapabilityAwareRouter`, a small pattern with no telecom code.

![Recovery Decision Inspector: Brazil cohort restored after a gated, human-approved profile switch](../screenshots/brazil-restored.png)

*Everything in SIMShift is simulated: devices, networks, eSIM profiles and management commands. No carrier, eUICC
or customer system is contacted. The Decider and Bedrock calls are real.*

## 1. The problem: the fast fix that makes things worse

Picture 3,200 asset trackers in Brazil that stop reporting. Each has a cellular modem and an eSIM that can hold more
than one subscription profile. The tempting fix is "switch them all to the other profile". Sometimes that is right.
Often it is not:

- **The network may be the problem.** Another operator on the *same* profile would fix it with no profile change.
- **The cellular link may be fine.** Devices register, but cloud ingestion broke. A profile switch fixes nothing.
- **The devices may be unreachable.** With no management path, an over-the-air command never arrives.
- **The firmware may be stuck in a reset loop.** No network-side action helps.
- **It may clear by itself.** A short congestion burst needs one retry, not a change.

Every recovery action is easy to execute. Picking the right next one is the hard part, and it happens many times per
incident, across many incidents. That is a bounded, typed choice, which is what a small decision model is for.

## 2. What SIMShift does

SIMShift works on incident cohorts, groups of devices with the same symptoms. For each incident it repeats one step:

1. **Observe** the cohort: attach, data-session, telemetry and heartbeat rates, the active profile, whether another
   operator or profile is available, whether a management path exists, and the evidence collected so far.
2. **Filter** the six options with a deterministic policy, and record why each removed option was removed.
3. **Decide**: Strands Decider 2B picks the next tool from what is left.
4. **Route** on Decider's confidence: act, gather read-only evidence, or fall back to a human.
5. **Act**: the chosen Strands tool runs against a deterministic digital twin, behind a gate that re-checks the policy.

It stops when service is restored (registration *and* application telemetry at 95% or more), when it escalates, or
after six steps.

## 3. The decision Decider 2B makes

Decider answers one typed `choice` question at every step:

> *Given the cellular connectivity symptoms, diagnostic evidence so far, and only these admissible tools, which next
> tool is most useful for safely advancing service restoration? Do not assume an unverified recovery path works.*

| Option | Strands tool | Kind |
|---|---|---|
| `retry_connection` | `simulate_retry_with_backoff` | bounded, network-side |
| `try_allowed_operator` | `simulate_operator_reselection` | another operator on the active profile |
| `investigate_device` | `query_firmware_modem_diagnostics` | read-only |
| `investigate_data_path` | `query_apn_session_app_diagnostics` | read-only |
| `evaluate_profile_change` | `prepare_guarded_profile_transition` | plan review, hard gate, human approval, then the virtual eIM |
| `escalate_or_wait` | `defer_or_escalate` | the fallback |

Here is step 3 of the recorded Brazil run. The policy had removed four options:
- **operator reselection**, because the active profile allows no other operator;
- **both diagnostics**, because they had already run;
- **retry**, because the serving network had rejected registration and a re-attach would meet the same reject and
  network back-off.

Two options were left. Decider answered:

```json
{"choice": "evaluate_profile_change",
 "probabilities": {"evaluate_profile_change": 0.9391, "escalate_or_wait": 0.0609},
 "confidence": 0.8781, "model": "strands-decider-2B-qwen3.5-v1-2610"}
```

The confidence is derived from the distribution as `(N·p_max − 1)/(N − 1)`. It is not a calibrated probability of
being right, and SIMShift treats it as a routing signal:

| Condition | Route |
|---|---|
| confidence ≥ 0.5 | act on Decider's choice |
| below 0.5, a read-only option is admissible | run the **most probable read-only** option |
| below 0.5, nothing read-only left | fall back to escalation |
| no answer, a malformed or inconsistent answer, or a choice outside the offered options | fall back |

In the Brazil run, Decider's first two answers leaned towards `retry_connection` at confidence 0.04 and 0.20. A retry
cannot help when the only operator on the profile is down, and the router did not act on it. It ran the data-path
check and then the modem check, which found reject cause #17 (synthetic, "network failure") from the serving
operator. With that evidence, the policy admitted the profile change, and Decider picked it at 0.88.

This only works because these depot trackers keep a Wi-Fi gateway path to the eIM that does not depend on the
failing profile. A device that cannot register has no cellular path for an over-the-air command. In the Germany
scenario management rides on cellular, so the profile change is removed there.

**The choice is causal.** The router calls `agent.tool.<selected>()`, a real Strands tool call. A test injects a
different admissible choice and asserts that a different tool runs.

## 4. Bedrock runs the loop and cannot pick the tool

SIMShift has a mode where a Strands agent on Bedrock (Claude Haiku 5.5, eu-central-1) drives the incident. That agent
sees exactly two tools:

- `get_incident_state()` returns the observable state.
- `advance_recovery()` runs one policy → Decider → gated-tool step and returns what happened.

Neither tool takes an argument. Bedrock decides when to look, when to keep going and how to write the report for a
NOC engineer. It has no parameter through which it could name a recovery tool, skip the policy or approve a profile
change. The tests run the real Strands event loop with a scripted model that tries to pass
`{"tool": "prepare_guarded_profile_transition"}` and check that Decider's choice still runs. In all six recorded
orchestrated runs, Bedrock kept calling `advance_recovery` until the incident was terminal, and Decider's answers
were identical to the six plain-loop recordings.

Bedrock also does two smaller jobs: it reviews a profile-change plan before the gate (its recommendation is shown to
the human approver, and the gate does not read it), and it explains finished runs.

## 5. Safety: hard checks, not trust

- **Filter before deciding.** Removed options are never shown to the model.
- **Re-check before acting.** The policy runs again as a Strands `InterventionHandler` before any routed tool, on
  every call path, and denies anything excluded.
- **Ten checks for a profile change.** eUICC support, rollback support, failing registration, a registration
  reject cause, no operator reselection available, an installed target, target coverage, a reachable management path,
  owner authorization, and a human approval bound to that exact proposal. The virtual eIM then checks the approval
  against its own proposal id, so even a broken gate could not push an unapproved switch.
- **A recorded profile-switch path.** Each attempt records `REQUESTED → VALIDATED → APPROVED → DELIVERED →
  RESULT_REPORTED → VERIFYING → SUCCEEDED`, or stops at `BLOCKED`, `NOT_DELIVERED`, `ROLLED_BACK` or
  `UNCONFIRMED`.
  - Verification always comes before success, and success needs registration, data session and application ACK.
  - A failed verification rolls back.
  - If the eUICC result never reaches the eIM, SIMShift does not read the silence as success. It accepts the switch
    only on independent evidence: the network sees the devices on an operator that only the target profile reaches,
    and service is restored. Otherwise it hands off without sending a second command. When the new profile cannot
    connect at all, the device rolls back on its own.
- **Telecom basics the model enforces.**
  - Registration alone is not service: Japan registers fine while telemetry fails.
  - Retries stop after a registration reject.
  - Commands are idempotent.
  - An approval issued against one profile state is refused once the state has moved on.
- **An independent audit.** A Strands hook records whether each executed tool was excluded in the state it ran in.
  It was zero in all six orchestrated runs and for every benchmark chooser; a test removes the gate to show the audit
  does catch a violation.

**The offline case.** These devices have no heartbeat and no management path. The policy removed device diagnostics,
operator reselection and the profile change. Decider chose a network-side check at confidence 0.06, routed as
read-only. The check found no attach attempts and no periodic registration updates. A device in power-saving mode
would still send those. Retrying could no longer reach anyone, so only escalation was left. In the UI you can force a profile change on a cloned twin: the gate blocks it with
`management_path_reachable` failed, the path reads `REQUESTED → BLOCKED`, and nothing is sent.

![OFFLINE: only escalation is left; a forced profile change on a clone is blocked](../screenshots/offline-blocked.png)

## 6. Results

**Six hand-written scenarios**, one recorded run each with the live Decider and Bedrock:

| Scenario | Outcome |
|---|---|
| Brazil: the only operator on the profile is down | restored after a gated, approved profile switch |
| Germany: primary network down, a second operator allowed | restored by operator reselection, no eSIM change |
| Japan: cellular healthy, ingestion broken | ingestion fault found and escalated, no network change |
| Offline: devices without power | escalated, no OTA command |
| Firmware loop | reset loop found and escalated to the device team |
| Transient congestion | restored by one retry |

**A benchmark on 60 generated incidents**, 10 per family, seeds the project never used for tuning. Five choosers
answered the same question through the same router, policy and gate. An escalation only counts as a correct end
for application and firmware incidents if the diagnostic that finds the cause ran first; handing off blind is not a
diagnosis.

| | rules | random | Decider | Bedrock | Bedrock + stated confidence |
|---|---:|---:|---:|---:|---:|
| Correct end state, with the evidence | 95.0% | 50.0% | **96.7%** | 91.7% | 93.3% |
| First action acceptable | 95.0% | 41.7% | **86.7%** | 83.3% | 81.7% |
| First choice = preferred tool | 95.0% | 28.3% | 50.0% | 81.7% | 81.7% |
| Mean simulated minutes | 52.3 | 61.5 | 54.5 | 52.0 | 51.2 |
| Chooser latency p50 / p95 | — | — | **106 / 123 ms** | 2,086 / 3,431 ms | 2,043 / 3,050 ms |
| Bedrock tokens (in / out) | — | — | **0** | 47,067 / 26,261 | 50,423 / 31,181 |
| Forbidden executions | 0 | 0 | 0 | 0 | 0 |

"Bedrock" names one option, so the router always acts on it. "Bedrock + stated confidence" also gives a 0–1
confidence, which goes through the same 0.5 threshold and read-only fallback as Decider's.

What I take from it:

- **Decider's confidence carries real signal.** All 17 first answers at confidence ≥ 0.5 picked the preferred tool.
  Below 0.5, only 13 of 43 did. Routing those uncertain answers to read-only checks is what got 58 of 60 incidents
  to the right end state. The 0.5 threshold was fixed before this run.
- **Bedrock's stated confidence carried none.** It was between 0.55 and 0.85 on all 98 answers that gave one, so the
  same threshold never held an answer back. Asking for a confidence ended one incident more correctly (93.3% vs
  91.7%), which a single run cannot separate from noise.
- **Bedrock picked better first tools but missed transients.** It picked the preferred first tool more often than
  Decider. On transient incidents, though, it nearly always started with modem diagnostics and then escalated
  instead of retrying: 5 of 10 for plain Bedrock, 4 of 10 with a stated confidence. 4 of its 99 answers were cut off
  at the output limit and went to the fallback.
- **Speed and cost.** About 20 times lower latency per choice, and no Bedrock tokens for routine choices. Decider ran
  on a laptop GPU (MLX on an Apple M4 Max) and Bedrock in eu-central-1, so this is the latency an agent built this way
  sees, not a like-for-like model comparison.
- **The guardrails kept even random choices safe.** No chooser made a forbidden execution or an unnecessary profile
  change. The chooser decides whether and how fast recovery happens.
- **Rules did well because rules can.** I wrote the runbook from domain knowledge, and these families are tidy. It
  checks the recent-firmware flag before the attach trend, so it missed the 3 transient incidents where that flag
  was a distractor. Real fleets are messier than both.

**Caveats.** The incidents are synthetic and the families were designed with signals that point to their causes. I
wrote the option descriptions. Each chooser ran once. Treat the table as evidence that the parts work together, not
as a field result. Every step's raw answer, tool result and twin event is committed next to the table, and a test re-derives the
table from those records.

## 7. Where Decider struggled

- **Brazil, first two steps.** Decider preferred `retry_connection`, the one thing that cannot help on a dead
  operator, though with low confidence. The routing caught it.
- **Japan, early version.** After finding the ingestion fault, Decider preferred a profile change. I added a
  deterministic rule: no profile change while the active profile registers normally.
- **Firmware loop.** After the diagnostics reported a reset loop, Decider still preferred retrying (p 0.75,
  confidence 0.50, twice). I added a rule: no retries once a reset loop is diagnosed.
- **Two generated firmware incidents.** Decider chose `retry_connection` at all six steps. The first, at low
  confidence, became a read-only data-path check; the next five ran as retries, and the step limit escalated
  without the modem diagnostics, so the reset-loop rule never fired. I left it unfixed: requiring modem diagnostics
  before any retry would be a rule written for this result.
- **Raw first picks.** In the benchmark, Decider's top choice was the preferred first tool only half the time.

The pattern in these fixes: when the model is wrong in a way a domain expert would call a rule, write the rule.
Leave the model the choices that depend on the evidence.

## 8. The reusable pattern: `CapabilityAwareRouter`

[`patterns/capability_aware_router/`](https://github.com/HDGoldi/simshift-agent/tree/main/patterns/capability_aware_router)

```python
from patterns.capability_aware_router.router import CapabilityAwareRouter, DeciderClient

router = CapabilityAwareRouter(
    decider=DeciderClient("http://127.0.0.1:8099"),
    instructions="Which next remediation step most safely restores the service?",
    options={"rollback_release": "Revert to the previous release; suits regressions after a recent deploy",
             "inspect_logs": "Read-only: look at recent error logs",
             "page_oncall": "Hand off to a human"},
    tools={"rollback_release": "rollback_release", "inspect_logs": "inspect_logs", "page_oncall": "page_oncall"},
    policy=lambda s: {} if s["previous_release_available"] else {"rollback_release": "nothing to roll back to"},
    fallback="page_oncall",
    read_only=frozenset({"inspect_logs"}),
)
agent = Agent(model=..., tools=[...], interventions=[router.gate(lambda: current_state)])
decision, result = router.step(agent, current_state)
```

You supply the options (with *when each one suits* in the description), a policy that returns
`{option: reason}` for whatever is inadmissible, a fallback and the read-only options. The router asks Decider,
checks the answer against the question, routes on confidence, calls the Strands tool, and gates every routed tool
call. `ReplayDecider` re-runs a saved trace without a Decider server. The folder has a web-service remediation
example and one test file per property, and a test checks that it imports nothing from SIMShift.

## 9. Limits and lessons

**Limits.** Not GSMA SGP.32: eIM, IPA and eUICC are simplified virtual models.
- **Cohorts, not devices.** One incident is one pre-segmented cohort, not individual devices, and a switch applies to
  the whole cohort at once.
- **Not modelled:** radio technologies, power-saving modes, forbidden-network lists and NAS timers. Neither is a
  device-local fallback profile. [docs/telecom-fidelity.md](https://github.com/HDGoldi/simshift-agent/blob/main/docs/telecom-fidelity.md)
  lists what is modelled, simplified and left out.
- **How the telecom side was checked.** We asked a self-hosted, telecom-tuned open-weight LLM to critique a written
  description of the design, and ran an LLM-assisted review that read the relevant 3GPP clauses but not the full GSMA
  SGP.32 v1.3 text. Neither saw the code. We checked each point against the code and turned the useful ones into
  rules, tests and that table. Nothing here is certified or standards-validated. The agent and Decider run locally today; only Bedrock runs on AWS. The planned deployment is
AgentCore Runtime for the agent and a private Fargate container for Decider, and no AWS latency is claimed until it
exists.

**Lessons.**
1. **Filter before the model sees the options.** It is simpler and safer than asking the model to avoid them, and
   "why this option was removed" became the most useful field in the trace.
2. **Confidence is a routing signal, not a truth score.** Acting only above 0.5 and gathering read-only evidence
   below it did more for correctness than any prompt change.
3. **Keep the answer out of the state.** My first probes sent the scenario ID, which hints at the answer. Tests now
   check that no hidden field reaches Decider, Bedrock or the UI.
4. **Let the big model run the conversation, not the tool choice.** Two zero-argument tools turned "Bedrock
   orchestrates" from a risk into a property you can test.

## 10. Links

- Code (Apache-2.0): https://github.com/HDGoldi/simshift-agent
- Reusable pattern: https://github.com/HDGoldi/simshift-agent/tree/main/patterns/capability_aware_router
- Measurements and benchmark: https://github.com/HDGoldi/simshift-agent/blob/main/docs/measurements.md
- Demo video (under 3 minutes): link added when published

*A good recovery agent knows when to switch, when to look first, and when to leave the fleet alone.*

`#strands-decider-2b` `#tool-selection`
