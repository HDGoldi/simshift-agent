# SIMShift vertical-slice architecture

## Overview

The first slice is a Python 3.11 CLI with one inspectable path: strict fixture load → typed observable projection → capability filtering → **real Decider HTTP choice** → explicit effective-choice policy → exact direct invocation of the matching Strands-registered tool → optional pure gates and atomic virtual-transition commit → separate registration and telemetry checks → one no-tools explanation → durable JSONL trace. Decider owns the model choice; a deterministic policy may conservatively replace it with escalation and records both values. Bedrock cannot preselect or authorize tools. All telecom behavior is synthetic.

Status: **IMPLEMENTED:** the local CLI, strict Decider adapter, direct Strands dispatch, deterministic simulator, profile gates, and atomic JSONL tracing. **VERIFIED:** offline contracts, Strands 1.61.1 direct-tool APIs, retained local artifact bytes/manifest chain, and opt-in local real-Decider/production-path tests. The declared base-repository revision remains inferred, not independently verified. **OBSERVED:** retained lossless UTF-8 health/request/response bodies with recomputed hashes and validated BR/OFFLINE traces from the pinned CPU Decider. **SIMULATED:** telecom, approval, transitions, and outcomes. **UNVERIFIED:** AWS/Bedrock account, deployment, GPU, accuracy, latency, and cost.

## Locked technology stack

Use CPython 3.11, `uv==0.12.18` with retained `uv.lock`, Pydantic `2.14.1` strict models, `strands-agents==1.61.1`, stdlib `argparse`, stdlib `http.client` for Decider HTTP, Strands `BedrockModel` for Bedrock Converse, JSON fixtures, JSONL traces, `pytest==9.1.1`, `ruff==0.17.1`, `mypy==2.4.0`, and required `bash -n` shell syntax validation. ShellCheck is optional enhanced lint because it is not present in the observed environment. New code is Apache-2.0. There is no FastAPI application, UI, database, or application container in this slice. CPU/CUDA Decider runtimes have separately hash-locked deployment constraints because accelerator compatibility has not been validated here.

`http.client` is chosen—not left to implementation—because it allows distinct connect/read timeouts and bounded body reads without another runtime dependency. Application code never imports Decider model internals.

## Repository and ownership

```text
pyproject.toml / uv.lock / LICENSE / NOTICE / README.md
src/simshift/
  cli.py                              CLI parsing, exit mapping, status disclosure
  config.py                           RunConfig, behavior/environment hashes
  domain/enums.py                     closed enums
  domain/models.py                    strict DTOs from all docs
  scenarios/repository.py             duplicate-safe load, split, incident lock/store
  decision/projection.py              ObservableIncident-only allowlists/canaries
  decision/filter.py                  telecom CapabilityFilter and stable reasons
  decision/coordinator.py             cardinality branch + model/effective policy
  integrations/decider_http.py        thin SIMShift wrapper around pattern client
  integrations/strands_tools.py       six @tool closures and Agent construction
  integrations/bedrock.py             real no-tools explainer + labeled local doubles
  orchestration/dispatch.py           exact Action-to-direct-call lambdas
  orchestration/runner.py             step/budget/run-state owner
  policy/profile_transition.py        pure gates, preview/final transaction coordinator
  simulator/engine.py                 only owner allowed to resolve EvaluatorTruth
  simulator/euicc.py                  transition/eUICC aggregate and idempotent dispatch
  verification/recovery.py            only service_restored owner
  tracing/events.py                   discriminated event DTOs/link validation
  tracing/recorder.py                 buffered atomic JSONL
scenarios/br_profile.json / offline.json
patterns/capability_aware_router/
  __init__.py
  schemas.py                          JSONValue, options, decision/no-decision/result
  filters.py                          CapabilityFilter protocol, FilterResult 0..255
  decider_client.py                   canonical strict HTTP transport/parser/validation
  router.py                           capacity-bounded choice call and exact registry invocation
  trace.py                            portable causal trace DTO
  examples/document_processing.py     non-telecom real-client example
  README.md
  tests/...
tests/unit/...                        fakes are under tests/fakes only
tests/integration/test_real_decider.py
tests/integration/test_production_path.py
tests/integration/test_aws_bedrock.py
infra/ec2/... / scripts/...
```

The standalone pattern client is the **only** implementation of Decider request serialization, duplicate-safe JSON parsing, response limits, probability/confidence validation, and basic one-attempt transport. It retains exact request and validated response bytes for the immediately completed exchange. `simshift.integrations.decider_http.SimshiftDeciderAdapter` imports it and adds: observable projection, full trusted-manifest-chain verification, health consistency checks, two bounded retries, and operation-boundary trace evidence. The coordinator emits policy evidence before dispatch; `DirectDispatcher` emits the authoritative action-to-registered-tool mapping before invocation and the strict result afterward. The CLI and integration tests use this same adapter/client path. Dependency direction is `simshift -> patterns`; the pattern never imports `simshift`. This removes duplicate protocol owners and post-hoc interaction reconstruction.

## Component boundaries and information flow

```text
CLI -> ScenarioRepository -> ScenarioRuntime
                              | observable -> filter/coordinator -> Decider adapter
                              | policy -----> ToolServices/proposal/gates
                              | truth handle ----------------------> VirtualFleetEngine only
coordinator -> dispatch allowlist -> StrandsToolHost -> ToolServices -> typed ToolExecution
profile ToolExecution -> transition coordinator -> VirtualEuiccEngine -> verifier
post-tool evidence -> Explainer -> trace/result
```

`ScenarioRepository` returns `ObservableIncident`, `PolicyMetadata`, and an opaque truth handle. `VirtualFleetEngine` is the only constructor that accepts the handle. Projection functions are statically typed to `ObservableIncident` and positively build output fields; no code removes fields from a raw fixture. `ToolServices` exposes separate observable/policy methods and has no truth accessor. Profile proposal preparation may read policy inventory. Diagnostic/retry methods ask `VirtualFleetEngine` to execute an action by typed enum; the engine internally resolves truth and returns only public observations/check inputs. Every evaluator fixture contains a unique non-public `EVAL_ONLY_*` canary. Sink validation rejects evaluator-only keys/paths, `HiddenCause`, serialized `EvaluatorTruth`/`ActionEffect`, private `_` keys, and that canary; it does not reject action/evidence strings that are independently defined by public DTOs.

Every tool has this exact public Strands signature and a strict dict result generated from `ToolExecution`:

```python
@tool
def simulate_retry_with_backoff(*, incident_id: str, observation_revision: int) -> dict: ...
@tool
def simulate_operator_reselection(*, incident_id: str, observation_revision: int) -> dict: ...
@tool
def query_firmware_modem_diagnostics(*, incident_id: str, observation_revision: int) -> dict: ...
@tool
def query_apn_session_app_diagnostics(*, incident_id: str, observation_revision: int) -> dict: ...
@tool
def prepare_guarded_profile_transition(*, incident_id: str, observation_revision: int) -> dict: ...
@tool
def defer_or_escalate(*, incident_id: str, observation_revision: int) -> dict: ...
```

`ToolServices.resolve(incident_id, observation_revision)` checks the run-scoped incident ID and exact current revision under the incident lock. Unknown incident is `UNKNOWN_INCIDENT`; mismatch is `STALE_OBSERVATION`; neither increments counts or calls the engine. Extra/missing arguments fail Strands/Pydantic schema validation. A strict `ToolExecution` contains `action`, `tool_call_id`, `status` (`APPLIED|PROPOSAL_PREPARED|ESCALATED|REJECTED`), `effect_class` (`STATE_CHANGE|OBSERVATION|PROPOSAL|TERMINAL|NONE`), input/output revisions, newly added `evidence`, optional reason/proposal/registration/telemetry records, and simulator version. Unknown fields and evaluator canaries are fatal normalization errors.

## Portable router contract

Portable models are frozen/strict:

- `QuestionOption(label, description)`: label `^[a-z][a-z0-9_]{0,63}$`, UTF-8 description 1–300 chars.
- `FilterResult(eligible, removed)`: 0–255 unique eligible options; removed entries contain original option and non-empty reason. Eligible and removed are disjoint and exactly partition the supplied options. Unknown/invented options fail.
- `TypedChoiceQuestion(name, instructions, options)`: constructed only after filtering; 2–255 unique options, name regex above, instructions 1–1,000 chars.
- `ChoiceDecision(model, model_choice, probabilities, confidence, usage, latency_ms, extensions)` follows `docs/decider-api.md`.
- `NoDecision(reason="INSUFFICIENT_CHOICE_CARDINALITY"|"UNSUPPORTED_CHOICE_CARDINALITY", eligible_count, capacity)` represents a locally non-dispatched result and contains no model choice.
- `DecisionPolicy(min_confidence, fallback_label)` returns `EffectiveDecision(model_choice, effective_choice, override_reason)`; confidence below floor uses `LOW_CONFIDENCE`.
- `ToolRegistry` is an immutable exact-label-to-callback map. No dynamic `getattr` uses model text.

`CapabilityAwareRouter` receives trusted `num_slots` from a deployment manifest plus verified `/health`; for this checkpoint it must equal 24. `route_filtered()` accepts only a validated `FilterResult`. At 0/1 it returns `INSUFFICIENT_CHOICE_CARDINALITY`; above `min(255, num_slots)` it returns `UNSUPPORTED_CHOICE_CARDINALITY`. These paths call neither Decider nor a tool. At 2 through capacity it constructs the question, calls the canonical client, applies injected `DecisionPolicy`, verifies the effective label is both eligible and registered (policy application fails closed if its configured fallback is not eligible), invokes exactly one callback, and returns `RouteResult` plus `RouterTrace`. It does not silently reduce options.

SIMShift's `DecisionCoordinator` records filtering and consumes the router result. Its filter invariant keeps `escalate_or_wait` eligible. For one eligible escalation it may directly set `effective_choice=escalate_or_wait`; zero or over-capacity is an internal/configuration failure, not a fabricated choice. Pattern tests cover 0, 1, 2, 24, 25, and 255 against capacity 24; 24 is structurally dispatchable and 25/255 never make HTTP calls.

The non-telecom document example options are `extract_text`, `inspect_metadata`, `request_human_review`; it filters by parser capability, reads a real loopback `STRANDS_DECIDER_URL`, and calls instrumented local callbacks. It imports no `simshift` symbol.

## Decision and Strands dispatch

SIMShift always traces these distinct values:

```text
model_choice: Decider label or null when Decider was not called
effective_choice: dispatched label
override_reason: null | LOW_CONFIDENCE | INSUFFICIENT_CHOICE_CARDINALITY
```

Default `DecisionPolicy(min_confidence=0.20, fallback_label="escalate_or_wait")` is uncalibrated. The real causal-wiring integration test injects `min_confidence=0`; this proves the actual model label controls the tool without weakening gates because all submitted labels are admissible and profile evaluation is proposal-only. A separate unit test proves the default override.

Exact dispatch lambdas all pass current typed state identity:

```python
DISPATCH = {
 "retry_connection": lambda i, r: host.tool.simulate_retry_with_backoff(incident_id=i, observation_revision=r),
 "try_allowed_operator": lambda i, r: host.tool.simulate_operator_reselection(incident_id=i, observation_revision=r),
 "investigate_device": lambda i, r: host.tool.query_firmware_modem_diagnostics(incident_id=i, observation_revision=r),
 "investigate_data_path": lambda i, r: host.tool.query_apn_session_app_diagnostics(incident_id=i, observation_revision=r),
 "evaluate_profile_change": lambda i, r: host.tool.prepare_guarded_profile_transition(incident_id=i, observation_revision=r),
 "escalate_or_wait": lambda i, r: host.tool.defer_or_escalate(incident_id=i, observation_revision=r),
}
```

Construction asserts all six exact tool names appear in `agent.tool_names`; mismatch is fatal. Direct `agent.tool.<name>` execution uses the verified Strands 1.61.1 executor without asking its model to select. No Bedrock invocation is active. The host model invocation counter must remain zero.

## CLI and input validation

`run` requires `--scenario BR_PROFILE|OFFLINE`, `--decider-url`, `--decider-manifest`, `--explainer bedrock|local-test-double`, and `--trace-out`. Optional inputs are `--seed` unsigned 32-bit (fixture default), `--approval granted|denied` (default denied), `--max-steps 1..4` (default 4), and `--confidence-floor` finite 0..1 (default 0.20). `--approval` is explicitly a `SCRIPTED_SIMULATED_INTENT`, not a startup grant: only after `ProfileTransitionProposal` is prepared and traced does the coordinator construct a grant bound to that proposal/run/incident/source/target. Unknown flags or unwritable output fail before adapters with exit 2. Repeated scalar options use standard `argparse` behavior, so the final occurrence wins.

`policy-check` accepts scenario, seed, `--action evaluate_profile_change`, and approval; it runs no Decider/Bedrock. `validate-fixtures` validates both files. Fixture limits are in `simulation-scope.md`.

Only literal `http://127.0.0.1:<port>` and `http://[::1]:<port>` Decider origins are accepted. Port is 1–65535; path is empty or `/`; userinfo, hostname DNS, HTTPS, query, fragment, and trailing custom paths fail. The adapter appends exact `/health` and `/v1/systemone`. There is no private-host opt-in in this same-host MVP. `DeterministicLocalExplainer` and `LocalTestDoubleModel` avoid AWS/network, but local-double runs still open the loopback Decider connection.

Bedrock mode requires `BEDROCK_REGION` plus `BEDROCK_INFERENCE_PROFILE` or `BEDROCK_MODEL_ID`; profile wins if both are present. It uses `BedrockModel(region_name=..., model_id=..., temperature=0.0, max_tokens=600, boto_client_config=Config(connect_timeout=5, read_timeout=60, retries={"max_attempts":2,"mode":"standard"}))`. The explainer agent has no tools and receives only sanitized observable/tool/gate/check evidence. Output is capped at 32 KiB and cannot alter result state.

## Run identity and deterministic behavior

`behavior_config_hash = SHA256(canonical JSON)` over only `fixture_revision`, seed, approval value, max steps, confidence floor, action registry version, simulator version, and gate-policy version. `run_id = SHA256("run\0" + scenario_id + "\0" + behavior_config_hash)[0:24]`.

`environment_evidence_hash` separately covers lockfile SHA, source revision when available, Decider endpoint class, trusted manifest SHA, explainer mode, Bedrock region/model reference, trace destination class, and observed Python/direct dependency versions. The full hash input record is retained in `run_started` and rehashed during trace validation. Credentials, raw account IDs, absolute user trace paths, and wall time are not hashed or traced. Changing only trace path/endpoint does not change run ID. Effect determinism and transition IDs are specified in `simulation-scope.md`.

## Gate transaction and state ownership

`ProfileTransitionPolicy.evaluate(snapshot, proposal, approval, transition_id)` is pure. `ApprovalGrant` can be created only after `proposal_prepared`; it carries and must exactly match `run_id`, `proposal_id`, `incident_id`, `source_profile_id`, and `target_profile_id`, and its deterministic ID hashes those bindings plus status. `TransitionCoordinator` performs preview, acquires one incident lock, checks duplicate audit/record, rereads state, performs pure final evaluation, then either creates a non-command `BlockedProposalAudit` or atomically reserves/consumes/creates `REQUESTED→VALIDATED→APPROVED`. The simulator alone advances `SENT` onward. Exact IDs, gates, lifecycle, duplicate behavior, and approval semantics are normative in `simulation-scope.md`.

Ownership is singular: Pydantic owns syntax/ranges; repository owns fixture split/cross-field checks/lock; pattern router owns protocol choice and registry matching; SIMShift filter owns telecom admissibility; decision policy owns model/effective choice; transition policy owns pure gates; coordinator owns atomic commit; eUICC engine owns one-active-profile and lifecycle; runner owns budgets; verifier owns restored status; recorder owns trace ordering/link validity.

## Trace event schemas and causal invariants

Every event has:

```text
schema_version="1.0"; event_id="<run_id>:<6-digit-sequence>"; run_id;
sequence>=0; logical_time>=0; event_type; component; component_status;
payload (event-specific strict object)
```

`component_status` is `REAL|LOCAL_TEST_DOUBLE|SIMULATED|UNVERIFIED`; run start contains independent status entries for `decider`, `strands_framework_dispatch`, `strands_tool_host_model`, `explainer_model`, `telecom_simulator`, and `aws_deployment`. Explainer provenance separately reports configuration and `invoked=false` at run start; the terminal event records observed invocation. Optional `wall_time_utc`/`duration_ms` are observation fields excluded from deterministic goldens.

Required event types and payload keys are:

| Event | Required payload/link fields |
|---|---|
| `run_started` | behavior/environment hashes, complete reproducible environment inputs, fixture revision, seed, bounds, statuses |
| `state_observed` | observation revision, sanitized state, state hash |
| `options_filtered` | decision ID, eligible labels, `{label,reason}` removals |
| `decider_health_checked` | manifest hash, expected/actual bounded health, lossless UTF-8 response body/hash, consistency result |
| `decider_request` | decision ID, lossless UTF-8 request body/hash, duplicate-safe decoded projection, attempt |
| `decider_response` | decision ID, lossless UTF-8 response body/hash, duplicate-safe decoded projection, `model_choice`, probabilities/confidence/usage/latencies |
| `no_decision` | decision ID, eligible count, trusted capacity, reason |
| `decision_policy_applied` | decision ID, nullable model choice, effective choice, floor, override reason |
| `tool_dispatch_started` | decision ID, tool-call ID, action, tool name, incident/revision |
| `tool_dispatch_finished` | tool-call ID, strict public `ToolExecution` |
| `proposal_prepared` | tool-call/proposal IDs, incident, source, target; precedes approval |
| `approval_materialized` | proposal/approval IDs, all binding fields, status, source=`SCRIPTED_SIMULATED_INTENT` |
| `gate_evaluated` | proposal ID, phase `PREVIEW|FINAL`, gate, pass, reason |
| `proposal_blocked` | proposal ID, final reasons; explicitly `command_created=false` |
| `approval_consumed` | proposal/transition/approval IDs; emitted only after atomic commit |
| `transition_changed` | proposal/transition/tool IDs, prior/new state |
| `duplicate_suppressed` | proposal/transition ID, operation, existing state |
| `registration_check` | check ID, cause tool/transition ID, occurrence, count/rate/threshold/pass |
| `telemetry_check` | check ID, cause tool/transition ID, occurrence, count/rate/threshold/pass |
| `bedrock_request` | explanation ID, sanitized prompt hash, provider/region/model ref |
| `bedrock_result` | explanation ID, bounded text, usage/latency when exposed |
| `bedrock_unavailable` | explanation ID, stable error class |
| `run_escalated|run_failed|run_completed` | terminal reason, latest check IDs, final profile/status, observed explainer invocation |

IDs are deterministic hashes of parent identity and ordinal. `decision_id` derives from run/iteration; `tool_call_id` from decision/effective choice; proposal/transition IDs follow `simulation-scope.md`; check IDs derive from causing tool/transition and check kind. The recorder rejects: response without request, tool without effective decision, proposal without matching tool, transition without passing final gates/commit, checks without a state-changing cause, completion-as-restored without both passing check IDs, and any evaluator canary.

The recorder recomputes request and response SHA-256 digests from the retained UTF-8 bytes, duplicate-safely decodes those exact bytes, compares decoded projections and decision semantics, then buffers validated events, writes a sibling temporary file, flushes/fsyncs, and atomically renames. It also rejects: response without request, tool without effective decision, proposal without matching tool, transition without passing final gates/commit, checks without a state-changing cause, completion-as-restored without both passing check IDs, false terminal explainer usage, and any evaluator canary. Pre-action trace-schema failure is fatal. Final rename failure exits 4 and prints a non-evidence result to stdout.

## Error behavior

- CLI/config/fixture/manifest path error: non-retryable, no dependency call, exit 2, ERROR.
- Manifest artifact hash failure or health inconsistency: non-retryable dependency/config failure, no Decider request/tool, exit 3, ERROR. Health is consistency evidence, not server attestation.
- Decider connection/read timeout, reset, 408/429/5xx: two retries after initial attempt at 0.25/0.50 seconds, WARNING; exhaustion `DEPENDENCY_ERROR`, exit 3. Other 4xx, redirects, oversized body, duplicate JSON keys, malformed schema/probabilities/confidence/choice: non-retryable protocol error, no tool, exit 3.
- 0/1 option result: no Decider; one eligible escalation is a safe domain path. Zero options violates SIMShift's filter invariant, exit 4, CRITICAL.
- Unknown/stale tool input: typed non-mutating rejection; runner escalates if possible, WARNING. Registry/Strands schema mismatch or truth leak: invariant failure, exit 4, CRITICAL.
- Gate denial: normal safe outcome; blocked audit only, approval unchanged, INFO. Atomic-store failure commits nothing and is fatal/internal.
- Simulated timeout/failure/check failure: domain result, no command retry or invented rollback, WARNING; observe once more if budget permits, then escalate.
- Bedrock runtime failure: bounded SDK attempts only; retain tool/simulation result and emit unavailable. CLI may end validly with optional explanation unavailable, but enabled AWS integration test fails.
- Storage/link failure: fatal exit 4, CRITICAL. Exit 0 means valid `RESTORED` or safe `ESCALATED`, not necessarily recovery.

## Test allocation

Pure unit tests cover every schema/cross-field invariant, fixture effects, structural leakage and unique canaries, filter/capacity boundaries 0/1/2/24/25/255, decision override, all six dispatch mappings, stale revisions, pure gates, proposal-before-approval ordering, all approval-binding mismatches, concurrent/duplicate commit, approval use, transition duplicate dispatch, both checks, IDs/hashes, bounds, trace links, and error mapping. Contract tests use a local scripted HTTP server against the canonical pattern client, including duplicate keys, redirects, timeout phases, and 65,537-byte bodies.

`real_decider` is opt-in and label-agnostically validates manifest/health/wire plus actual-label dispatch with confidence floor zero. `production_path` is separately opt-in and uses the exact production request/default policy to require the complete BR restored path plus a real-Decider OFFLINE no-transition path; model semantic drift fails this characterization. `aws_integration` repeats both production paths without provisioning and invokes real no-tools Bedrock only after BR tool/gate/check evidence. Every marker skips only while its explicit environment opt-in is absent; once opted in, missing configuration or any dependency/semantic failure is a test failure. Default tests need no network, weights, Docker, credentials, native ShellCheck, or cloud.

## Sources

Project architecture constraints: [`SIMShift_Project_Handoff.md`](../../SIMShift_Project_Handoff.md), §§0, 4–7, 14. Qualification: [`SIMShift_Hackathon_Requirements_and_Rules.md`](../../SIMShift_Hackathon_Requirements_and_Rules.md), §§2 and 7. Verified Decider API: [`.agents/tasks/decider-research.md`](../.agents/tasks/decider-research.md). Verified Strands direct-call and Bedrock constructor: [`.agents/tasks/strands-aws-research.md`](../.agents/tasks/strands-aws-research.md). Dev-tool release pins were checked against PyPI metadata on 2026-10-18; `uv.lock` is normative. Exact external links and access dates are in those research ledgers.