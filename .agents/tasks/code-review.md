# Real Decider-driven SIMShift recovery with guarded virtual profile switching

SIMShift implements the local BR_PROFILE/OFFLINE vertical slice with a pinned loopback Decider, direct Strands-registered tool dispatch, deterministic synthetic telecom effects, approval-bound virtual profile transitions, and retained causal traces. The actual BR evidence shows `evaluate_profile_change` selecting `prepare_guarded_profile_transition`, while OFFLINE selects safe escalation and the forced policy path blocks without a command, approval consumption, or profile mutation. The terminal gate-denial branch has the required adjacent `proposal_blocked` then `run_escalated(PROFILE_PROPOSAL_BLOCKED)` events and returns without another Decider, tool, host-model, or explainer call. Recorded verification is broad and honestly leaves AWS, real Bedrock, real telecom behavior, performance, and cost unverified.

Watch for: **confirmed** the BR trace records `SUCCEEDED` before its registration and telemetry evidence; **confirmed** production trace/explainer sinks do not receive or intrinsically reject fixture canaries; **confirmed** the standalone client can serialize non-string state keys into duplicate outbound JSON names; **confirmed** approval provenance uses a lowercase value that contradicts the documented exact contract.

**Verdict**: NEEDS_CHANGES

## High-level view

The decision path is genuinely causal. SIMShift constructs an observable-only state, filters options before inference, verifies the local artifact/health chain, preserves model and effective choices separately, and routes the effective enum through one explicit `agent.tool.<name>` branch; retained real-Decider bodies and matching tool events support that chain.

Profile execution is isolated from selection. The profile tool only prepares a proposal, approval binds every proposal identity field, all five gates are rerun under the incident lock, and only a committed record reaches the virtual eUICC. Final denial is terminal and OFFLINE removes retry, operator reselection, and profile evaluation before inference.

**Confirmed:** the virtual engine computes distinct registration and telemetry checks before deciding restoration, but the trace writes `VERIFYING → SUCCEEDED` before either check event. The review artifact therefore overstates when success became evidenced even though the in-memory result uses both checks.

Truth remains isolated along the normal typed path: only the fleet engine resolves the opaque handle, model projections are positive allowlists, and public tool results contain no evaluator DTO. **Confirmed:** the advertised sink-level canary backstop is inactive in production because trace and explanation validation use an empty canary set.

The standalone pattern is independent of `simshift`, enforces cardinality without option reduction, and dispatches through an immutable callback registry. **Confirmed:** its public client does not recursively validate state keys before `json.dumps`, leaving ambiguous duplicate member names possible for untyped callers.

Recorded evidence supersedes FEAT-004's earlier NOT RUN status: the final report records 121 passing default tests, 40 passing standalone tests, clean Ruff and mypy, successful license and shell checks, and enabled real-Decider/production-path success. A narrow hash spot-check confirmed all six retained hashes; AWS integration remains an actionable opt-in skip, and executable project paths contain no Git, cloud mutation, deployment, provisioning, or publication command.

<details>
<summary>Issues (4)</summary>

1. **Recovery evidence ordered after success** — **confirmed:** the BR trace emits `VERIFYING → SUCCEEDED` before registration and telemetry checks. Emit both checks before the terminal transition edge and reject this reversed order in trace validation.
2. **Canary guard not wired to sinks** — **confirmed:** production trace and explainer validation use no fixture canaries, so canary text under an allowed field bypasses the claimed sink backstop. Reject the reserved canary pattern intrinsically or wire a leak guard into every sink, with sink-level tests.
3. **Ambiguous standalone request JSON** — **confirmed:** `DeciderClient.choose()` lets `json.dumps` coerce non-string state keys, which can create duplicate outbound member names. Recursively validate string-only JSON object keys before HTTP and add an ambiguous-key regression.
4. **Approval source contract mismatch** — **confirmed:** retained traces use `scripted_simulated_intent` while requirements and docs specify `SCRIPTED_SIMULATED_INTENT`. Use and schema-constrain the documented literal.

</details>

<details>
<summary>Details</summary>

## Success is traced before the checks that establish it

`VirtualEuiccEngine.dispatch()` computes both layer checks and asks `RecoveryVerifier` for their conjunction before selecting the terminal transition state. The trace adapter loses that causal ordering: `SimshiftRunner._record_transition()` emits every transition edge, including `VERIFYING → SUCCEEDED`, and only afterward calls `_record_checks()`.

**Confirmed concern:** the retained BR trace has `SUCCEEDED` at sequence 28, followed by registration and telemetry checks at sequences 29 and 30. The production contract describes `ENABLED → checks → SUCCEEDED → RESTORED`; an inspectable trace must not claim terminal transition success before recording the evidence that permits it. Emit transitions through `VERIFYING`, then both checks, then the `SUCCEEDED|FAILED` edge; make `validate_event_sequence()` reject a terminal post-verification transition unless both matching checks already exist; and add an order-sensitive production-path regression instead of presence-only assertions.

## Fixture canaries are not enforced at production sinks

The repository removes `_evaluator_truth` before public DTO construction, `TruthHandle` is resolved only by `VirtualFleetEngine`, and retained requests, tool results, traces, and explanations contain no hidden values. **Confirmed concern:** `assert_no_evaluator_leak()` rejects canary text only when its caller supplies `canaries`; `TraceEvent.validate_event()` and both explainers call it without canaries, while the CLI constructs `TraceRecorder(args.trace_out)` with the default empty tuple. The only canary-aware call is a unit test that passes a literal manually, so an `EVAL_ONLY_*` value under an otherwise permitted sink field would not trigger the claimed production backstop. Reject the reserved canary pattern intrinsically, or pass a non-secret leak guard from fixture loading into every trace, tool/log, and explanation sink, then test each sink with fixture canaries.

## Standalone state serialization can create duplicate JSON member names

The reusable router has no telecom import, its response parser rejects duplicate keys, and independent tests cover cardinality 0/1/2/24/25/255 and exact callback dispatch. **Confirmed concern:** `DeciderClient.choose()` checks only that state is a `str`, `list`, or `dict` before serializing it. Python JSON encoding accepts non-string mapping keys and coerces them to strings, so distinct keys such as integer `1` and string `"1"` can produce duplicate outbound member names. Recursively validate the public `JSONValue` contract—especially string-only object keys—before encoding, and prove ambiguous state fails before HTTP.

## Approval provenance casing contradicts the declared trace contract

Proposal creation precedes approval materialization, and the grant binds run, proposal, incident, source, target, and status. **Confirmed concern:** `runner.py` emits `source="scripted_simulated_intent"`, while `requirements.md`, `docs/architecture.md`, and `docs/simulation-scope.md` specify exact value `SCRIPTED_SIMULATED_INTENT`. `TraceEvent` accepts any source value, so validation cannot catch the mismatch. Use the documented literal consistently and constrain the event schema/test so retained evidence cannot drift from the claims contract.

## Terminal denial, OFFLINE safety, and provenance separation

A profile denial stores only `BlockedProposalAudit`, leaves command creation and approval consumption false, emits `proposal_blocked`, immediately emits `run_escalated(PROFILE_PROPOSAL_BLOCKED)`, and returns. Focused evidence establishes one provider call, one Strands dispatch, one audit, no transition, zero host/explainer calls, and required terminal adjacency.

OFFLINE filtering removes all three remote mutation routes before the model request. The observed run dispatches `defer_or_escalate` with no transition lifecycle and retains `profile_A`; the forced policy command reports `MANAGEMENT_UNREACHABLE`, null transition, unchanged observable/policy state and profile, no command, and unconsumed approval. Run-start provenance independently identifies `strands_framework_dispatch=REAL`, `strands_tool_host_model=LOCAL_TEST_DOUBLE`, and `explainer_model=LOCAL_TEST_DOUBLE`, with the host model uninvoked.

## Recorded verification and claim boundaries

Final evidence records `121 passed, 3 skipped` for the default suite, `40 passed` for the standalone pattern, clean Ruff, strict mypy over 47 source files, 92 valid license headers, shell syntax validation, fixture validation, and the forced OFFLINE result. Default opt-in runs give exact setup actions; enabled local real-Decider and production-path tests passed without substituting a fake and produced retained BR/OFFLINE bodies and traces. This review did not rerun those suites; its one narrow spot-check recomputed the six documented SHA-256 values and matched all of them.

AWS and real Bedrock remain `UNVERIFIED`, telecom and approval remain `SIMULATED`, and the base Hub revision remains inferred rather than independently proven. Deferred EC2 documents do not claim implemented deployment assets. No prohibited operation was performed during this review. The supplied evidence attests that none occurred during implementation; inspection independently confirms executable project paths contain no Git, cloud mutation, deployment, provisioning, upload, or publication command. A preserved upstream Decider snapshot contains Git metadata, so absence of historical Git activity is an attested limitation rather than something source inspection alone can prove.

</details>

<details>
<summary>File map</summary>

- `patterns/capability_aware_router/` — independent strict Decider client, capability partition, capacity-aware callback router, example, and tests.
- `src/simshift/domain/`, `scenarios/`, and `src/simshift/scenarios/` — closed synthetic schemas, normative fixtures, truth split, and incident aggregate.
- `src/simshift/decision/` and `src/simshift/integrations/` — observable projection, filtering, artifact/health validation, model policy, registered tools, and explainers.
- `src/simshift/orchestration/`, `src/simshift/policy/`, `src/simshift/simulator/`, and `src/simshift/verification/` — direct dispatch, bounded runner, gate transaction, virtual lifecycle, deterministic effects, and dual-check recovery.
- `src/simshift/tracing/` and `src/simshift/cli.py` — provenance, causal validation, atomic JSONL output, command contracts, and exit mapping.
- `tests/`, `scripts/`, `.agents/evidence/vertical-slice/`, and `.agents/tasks/*evidence*` — offline/opt-in verification, capture and validation scripts, retained traces, and recorded results.
- `README.md`, `docs/`, `infra/ec2/`, `pyproject.toml`, `uv.lock`, `LICENSE`, and `NOTICE` — usage, claims boundaries, deferred cloud backlog, reproducible package metadata, and licensing.

A Git diff is unavailable at the project root and Git operations are prohibited; this review covers the supplied implementation and evidence tree directly.

</details>
