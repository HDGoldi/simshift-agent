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

Code: [`simshift/agent.py`](../simshift/agent.py) (loop and tools), [`simshift/policy.py`](../simshift/policy.py)
(exclusions and gate), [`simshift/simulator.py`](../simshift/simulator.py) (twin and virtual eIM),
[`patterns/capability_aware_router/router.py`](../patterns/capability_aware_router/router.py) (the reusable pattern).

## Role boundaries

| Component | Owns | Does not own |
|---|---|---|
| Strands Decider 2B | choosing the next tool among admissible options; its probabilities and derived confidence | authorization, network state, safety |
| Router (pattern) | turning a choice and its confidence into a route; calling the Strands tool | diagnosis |
| Strands agent | tool registry, tool execution, intervention hooks, message history | simulated outcomes |
| Amazon Bedrock (Claude Haiku 5.5) | reviewing profile-change plans (advisory); explaining the outcome | selecting the routine next tool; authorizing any change |
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

Independently of the gate, the virtual eIM refuses an enable command that carries no approval, and one it cannot
deliver because the management path is down. It does not repeat the gate's other checks.

Retries are bounded at 5 and excluded once registration is healthy. Read-only diagnostics run once per incident. The loop stops after 6 steps and escalates.
