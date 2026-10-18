# SIMShift: When Not to Switch

**An IoT connectivity recovery agent that uses Strands Decider 2B to choose the next safe tool. Amazon Bedrock explains each choice, and a digital twin shows what happens next.**

`#strands-decider-2b` `#tool-selection`

> ⚠️ **Everything is simulated.** All devices, networks, eSIM profiles and management commands are synthetic. Nothing here talks to a real carrier, eUICC, SM-DP+ or eIM. This is not a GSMA SGP.32 implementation.

## The decision Decider makes

> *Given the current cellular connectivity symptoms, existing diagnostic evidence, and admissible tools, which next tool is most useful for safely advancing service restoration?*

| Option | Tool | Limit |
|---|---|---|
| `retry_connection` | `simulate_retry_with_backoff` | Bounded retries |
| `try_allowed_operator` | `simulate_operator_reselection` | Only networks the active profile permits |
| `investigate_device` | `query_firmware_modem_diagnostics` | Read-only |
| `investigate_data_path` | `query_apn_session_app_diagnostics` | Read-only |
| `evaluate_profile_change` | `prepare_guarded_profile_transition` | Opens a guarded workflow; never enables a profile itself |
| `escalate_or_wait` | `defer_or_escalate` | Hands off to a human |

A deterministic policy removes options that aren't allowed **before** Decider sees the list. Decider's choice is the option whose tool runs.

## Reusable pattern

➡️ [`patterns/capability_aware_router/`](patterns/capability_aware_router/README.md) has no domain code. It contains the typed question, options, policy filter, Decider client, and tests.

## Status

| Part | State |
|---|---|
| Decider 2B routing (real model, CPU) | ✅ working, tested |
| Capability-Aware Router pattern + tests | ✅ |
| 3 synthetic scenarios (Brazil, Offline, Japan) | ✅ fixtures |
| Strands agent + Amazon Bedrock | ✅ wired and tested with a stand-in model; ⚠️ live Bedrock call not yet run |
| Digital twin outcomes, virtual eIM/eUICC, counterfactual replay | ✅ deterministic, seeded, tested |
| AWS deployment | ⏳ |
| Web UI (decision trace) | ✅ inspector, human approval gate, eUICC panel, counterfactuals |
| Evaluation harness | ✅ 6 families, dev/held-out splits, rules / random / Decider / Bedrock comparators ([latest results](evaluation/results/)) |

## Quick start

```bash
make install            # core + Strands + dev tools
make install-decider    # CPU torch + strands-decider==0.1.0
make serve-decider      # terminal 1: model on 127.0.0.1:8099 (~10 GB RAM on CPU)
make run                # terminal 2: route the 3 scenarios, trace -> logs/trace.jsonl
make test               # unit tests, no model needed
make test-live          # checks the real model answers
```

Pinned model: `StrandsAgents/strands-decider-2B-qwen3.5-v1-2610` @ `216d1ccb46a9e9b036eb9187b248db98480f77d4`.

Full agent (Strands + Bedrock + Decider). Needs an AWS identity allowed to call Bedrock:

```bash
export SIMSHIFT_AWS_PROFILE=<profile>          # optional; default credential chain otherwise
export SIMSHIFT_AWS_REGION=eu-central-1
export SIMSHIFT_BEDROCK_MODEL=<enabled model or inference-profile id>
.venv/bin/python -m agent.main --agent
SIMSHIFT_LIVE_BEDROCK=1 make test-live
```

**Who decides what.** Bedrock runs the Strands loop and writes the report. It sees only `get_incident_state` and `advance_recovery`, which takes **no arguments**, so it cannot name a recovery action. Inside `advance_recovery`, the policy filters options, Decider picks one, and that option's tool runs.

## Layout

```text
agent/        tools (simulated stubs), CLI runner; Strands + Bedrock next
decider/      SIMShift's question, options and policy for the router
patterns/     capability_aware_router/  ← the reusable recipe
simulator/    synthetic scenario fixtures (observable vs evaluator_only)
evaluation/   benchmark harness (planned)
infra/        AWS deployment (planned)
web/          decision-trace UI (planned)
tests/        SIMShift-level tests
spike/        first proof that Decider routes a tool (kept for reference)
```

## License

[Apache-2.0](LICENSE)
