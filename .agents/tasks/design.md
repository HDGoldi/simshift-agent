# SIMShift first working vertical slice — implementation design

## Overview

Implement a CLI-first Python vertical slice whose primary evidence is a real causal chain: load a strict seeded synthetic cohort → capability-filter tools → submit one typed choice to the pinned real Strands Decider 2B service → preserve the returned `model_choice` and derive an explicit `effective_choice` → directly invoke exactly the corresponding registered Strands tool → for profile proposals, run pure deterministic gates and one atomic commit → simulate only virtual eUICC/eIM/IPA state → verify registration and application telemetry independently → optionally ask a no-tools Bedrock agent to explain already-produced evidence. The design intentionally defers UI polish and cloud execution while making local code, opt-in integrations, and AWS artifacts implementable without unresolved architecture choices.

At design time, production code is **NOT IMPLEMENTED**. Decider wire behavior and Strands APIs are **VERIFIED**, the preserved local Decider smoke is **OBSERVED**, all telecom behavior is **SIMULATED**, and Bedrock account/model, AWS deployment, GPU behavior, domain accuracy, latency, and cost are **UNVERIFIED**. These labels are emitted independently at runtime.

## Locked stack and chosen alternatives

Use CPython 3.11, Pydantic `2.14.1` strict models, `strands-agents==1.61.1`, Strands `BedrockModel`, stdlib `argparse`, stdlib `http.client`, JSON/JSONL, `uv==0.12.18` plus committed `uv.lock`, `pytest==9.1.1`, `ruff==0.17.1`, `mypy==2.4.0`, `cfn-lint==1.57.2`, and required zero-install `bash -n` shell syntax checks. ShellCheck is an optional enhanced lint because it is absent from the observed host and no native bootstrap is required by this slice. License new work Apache-2.0 and retain notices. This stack is locked for the slice.

`http.client` is chosen over `urllib` because separate 2-second connect and 30-second read timeouts plus a 64 KiB bounded read are explicit with it. FastAPI, React, a database, and an app container are deferred because a CLI/trace better proves causality with fewer dependencies. Decider remains a separate loopback service rather than an in-process application dependency so CPU/CUDA stacks can be pinned independently. The AWS target is one persistent x86_64 EC2 host in `eu-central-1`; an offline S3 bundle and private AWS endpoints are chosen over NAT-time PyPI/Hugging Face downloads. AgentCore microVM is rejected for this checkpoint because observed CPU RSS exceeds its documented 8 GiB session maximum.

Bedrock tool selection is explicitly rejected: it would make Decider decorative. The registered Strands host is called through `agent.tool.<name>` after Decider, and a separate no-tools agent explains the result. An intervention hook is unnecessary for the primary path; deterministic policy rechecks provide the defense-in-depth boundary.

## Files and exact boundaries

Create the tree in [`../../docs/architecture.md`](../../docs/architecture.md). The critical implementation ownership is:

- `patterns/capability_aware_router/decider_client.py` is the **canonical** Decider HTTP serializer/parser/validator/one-attempt transport. It is domain-independent.
- `src/simshift/integrations/decider_http.py` wraps that client only for observable projection, trusted manifest and exact health checks, retries, tracing, and domain conversion.
- `src/simshift/decision/{filter,coordinator}.py` owns telecom eligibility, local no-decision/capacity handling, and `model_choice` versus `effective_choice` policy.
- `src/simshift/integrations/strands_tools.py` constructs six exact `@tool` closures around injected run-scoped `ToolServices`; it contains no evaluator truth.
- `src/simshift/orchestration/dispatch.py` contains the six immutable direct-call lambdas; `runner.py` owns four-step and action budgets.
- `src/simshift/policy/profile_transition.py` contains pure gate functions and the incident-lock atomic transaction coordinator.
- `src/simshift/simulator/{engine,euicc}.py` alone resolves evaluator truth and advances virtual state.
- `src/simshift/verification/recovery.py` alone computes restored status from two fresh checks.
- `src/simshift/tracing/{events,recorder}.py` owns discriminated events, link validation, canary rejection, and atomic JSONL.
- `src/simshift/integrations/bedrock.py` contains the real no-tools explainer, `DeterministicLocalExplainer`, and inert `LocalTestDoubleModel`.
- `scenarios/*.json` implement the exact complete values in [`../../docs/simulation-scope.md`](../../docs/simulation-scope.md).
- `infra/ec2/` and `scripts/` implement the offline private-subnet design in [`../../docs/aws-deployment.md`](../../docs/aws-deployment.md).

`patterns/capability_aware_router/` cannot import `simshift`. SIMShift imports its protocol client/router DTOs. Tests verify the exact canonical client used by CLI rather than a duplicate.

## External inputs and validation

`run` requires `--scenario BR_PROFILE|OFFLINE`, `--decider-url`, `--decider-manifest`, `--explainer bedrock|local-test-double`, and `--trace-out`. Seed is an unsigned 32-bit integer with fixture default; `--approval granted|denied` defaults denied and is only a scripted simulated intent captured at startup—not an `ApprovalGrant`; max steps is 1–4 default 4; confidence floor is finite 0–1 default 0.20. If profile evaluation prepares a proposal, the CLI traces/prints its incident, source, target, and proposal ID, then materializes the intent as a grant bound to exactly those values. Unknown/duplicate flags, bad output path, or bad values fail before constructing a model/client, exit 2.

The Decider origin is only literal `http://127.0.0.1:<port>` or `http://[::1]:<port>`. Reject DNS names, userinfo, TLS, query, fragment, redirect, custom path, control characters, and invalid ports. There is no private-host flag because local and chosen AWS deployments are same-host. The canonical client connects with 2 seconds, switches the socket to a 30-second read timeout, sends `Connection: close`, and reads at most 65,537 bytes to enforce a 64 KiB cap. Strict UTF-8 JSON uses duplicate-detecting `object_pairs_hook` at every depth. Details and exact response semantics are normative in [`../../docs/decider-api.md`](../../docs/decider-api.md).

A real Decider run requires a trusted local manifest with exact source `930e...`, checkpoint `216d...`, base `b148...`, expected health fields including exact `num_slots=24`, explicit logical file/Merkle references, artifact hashes/sizes, and CPU/CUDA lock. Deployment/local setup verifies the external archive digest, every internally manifested regular file, logical artifact roots, and upstream export/provenance before startup. Adapter health requires exact status/model/checkpoint/base/device/max-length/vision and exactly 24 slots. Health strings are consistency evidence only; they do not attest artifacts.

Fixtures are UTF-8, duplicate-free, finite, at most 256 KiB, with no URL/external reference or unknown field. Exact enums, models, cross-field checks, and complete fixtures are in `simulation-scope.md`. Repository loading returns three typed parts; no all-fields dictionary crosses an integration boundary.

Bedrock mode requires `BEDROCK_REGION` and either `BEDROCK_INFERENCE_PROFILE` or `BEDROCK_MODEL_ID`; profile wins and selection is traced. Local explainer components do not inspect AWS credentials or perform network I/O, but the run still calls the real Decider loopback HTTP service. `policy-check` accepts only `evaluate_profile_change` and runs no model. `validate-fixtures` validates both fixtures.

## Schemas, truth isolation, and simulator behavior

Use frozen `extra="forbid"` Pydantic DTOs. `ObservableIncident`, `PolicyMetadata`, `EvaluatorTruth`, profile/operator/channel records, `ActionEffect`, and fixture consistency rules are exact in `simulation-scope.md`. Evidence is a closed 18-value enum. Every fixture supplies retry occurrences 1/2 and occurrence 1 for every other action, so any allowed Decider route has a defined effect. Diagnostic actions add occurrence-specific evidence; retry/operator effects define check probabilities; profile evaluation defines target, delivery outcome, and post-enable probabilities; escalation is terminal.

`EvaluatorTruth` is held behind an opaque repository handle and only `VirtualFleetEngine` accepts that handle. Every evaluator fixture carries a unique `EVAL_ONLY_*` canary that cannot equal a public enum/string. Decider and Bedrock projectors accept only `ObservableIncident` and positively construct allowlisted DTOs; they never sanitize a broad fixture by deletion. Tools receive only incident ID/revision and resolve typed observable/policy data from injected `ToolServices`; only proposal preparation sees policy inventory. Engine output is a public DTO and cannot serialize `EvaluatorTruth`, `ActionEffect`, `HiddenCause`, evaluator-only keys/paths, or the canary. Values independently defined by public schemas, including action/evidence strings, may legitimately recur. Structural leakage tests inspect encoded requests, tool inputs/results, trace, stderr logs, and explanation prompts.

Cohort outcomes use SHA-256 of fixture revision, seed, action, occurrence, check kind, and device index. Registration and telemetry use separate streams. This makes repeated attempts defined and reproducible without global randomness. Both checks always run after state-changing actions, and only `RecoveryVerifier` can set restored.

## Filtering, model/effective decisions, and direct dispatch

The telecom filter starts with all six fixed options. It records every removal. It removes profile evaluation for missing target/unreachable management/transition exhaustion, operator reselection when the active profile has no permitted available alternative, remote retry for unreachable `OFFLINE` or retry exhaustion, and each diagnostic after its first occurrence. It always keeps escalation; the standalone protocol does not impose that domain rule.

Portable `FilterResult` permits 0–255 options and must exactly partition originals. The router is configured with trusted engine `num_slots` from manifest-verified health and is the single cardinality owner. For `2 <= n <= min(255, num_slots)` it builds the typed question and calls Decider. For 0/1 it records `NoDecision(INSUFFICIENT_CHOICE_CARDINALITY)`; for larger `n` it records `NoDecision(UNSUPPORTED_CHOICE_CARDINALITY, eligible_count=n, capacity=num_slots)`. Neither branch calls HTTP or a tool, and no deterministic reduction is performed because silently discarding caller options would change the question. SIMShift may directly dispatch escalation only for the one-option domain case where escalation remained eligible; zero or over-capacity is an invariant/configuration outcome, not an excuse to fabricate options. The pinned deployment requires `num_slots=24`; tests exercise 24 success structurally and 25/255 local non-dispatch.

A validated Decider response produces `model_choice`. `DecisionPolicy` produces `effective_choice`. At default confidence below 0.20 it retains the model choice but sets effective escalation and `LOW_CONFIDENCE`; confidence never authorizes a profile transition. The real causal-wiring test injects floor zero so the actual returned label calls its matching tool. This is safe because options are prefiltered and profile evaluation only proposes. A separate test proves default override.

Every tool has exact keyword-only `(incident_id: str, observation_revision: int)` arguments. `ToolServices.resolve` rereads state and rejects unknown/stale revisions before mutation. The fixed mapping is:

| Effective label | Registered direct Strands tool | Result class |
|---|---|---|
| `retry_connection` | `simulate_retry_with_backoff` | state-change candidate |
| `try_allowed_operator` | `simulate_operator_reselection` | state-change candidate |
| `investigate_device` | `query_firmware_modem_diagnostics` | read-only observation |
| `investigate_data_path` | `query_apn_session_app_diagnostics` | read-only observation |
| `evaluate_profile_change` | `prepare_guarded_profile_transition` | proposal only |
| `escalate_or_wait` | `defer_or_escalate` | terminal safe outcome |

Host construction asserts these six tool names are registered. Dispatch calls exact `agent.tool.<name>(incident_id=..., observation_revision=...)`; no arbitrary `getattr` consumes model text. `ToolResult` contains action/effect class, input/output revision, evidence, status/reason, optional proposal/check trigger, and simulator version. The tool-host model is never invoked. In local-explainer mode its inert model and the deterministic explainer are separately labeled `LOCAL_TEST_DOUBLE`; Decider and Strands dispatch are still `REAL`, telecom is `SIMULATED`, AWS deployment `UNVERIFIED`.

## Pure gates and atomic transition lifecycle

The proposal target is the lexicographically first eligible installed-disabled owner-matching profile. `proposal_prepared` is durably recorded before approval creation. The CLI's approval intent then creates `ApprovalGrant(approval_id, run_id, proposal_id, incident_id, source_profile_id, target_profile_id, status)`; its ID hashes every binding value plus status as specified in `simulation-scope.md`. The approval gate compares every binding field to the current proposal and rejects mismatch/staleness before consumption. Deterministic proposal/transition IDs and the other four exact gate rules are also in `simulation-scope.md`. `ProfileTransitionPolicy.evaluate` is pure: neither preview nor final pass consumes approval, reserves a key, creates state, or increments counters.

The coordinator previews all gates, acquires the incident lock, first returns an existing proposal audit/transition for duplicates, rereads state, and evaluates all gates again. Final denial creates only one `BlockedProposalAudit`; `BLOCKED` is not a transition state or command. It leaves transition count, in-flight state, idempotency key, and approval untouched. Final pass atomically reserves `(run_id, transition_id)`, consumes approval, increments the transition count/sets in-flight ID, and creates one record with `REQUESTED`, `VALIDATED`, and `APPROVED`. Any store error commits nothing. This sequencing prevents the second gate pass from failing on the coordinator's own mutation and prevents fresh IDs from evading duplicate suppression.

The virtual engine alone advances `SENT`. `ACK` proceeds to `ACKNOWLEDGED`, atomically switches one active profile at `ENABLED`, performs both checks in `VERIFYING`, and ends `SUCCEEDED` only if both pass; otherwise `FAILED`. Delivery may end `TIMED_OUT`/`FAILED` before enable without profile mutation. Duplicate simulator dispatch returns the existing record and emits suppression, with no repeated state/effect. No rollback is invented.

For `BR_PROFILE`, operator reselection is filtered; profile evaluation can produce `profile_B`; denial yields blocked audit; the approved deterministic fixture path can pass both checks. For `OFFLINE`, retry/operator/profile actions are filtered; cached diagnostics or escalation remain. Forced `policy-check` fails reachability, consumes no approval, creates no transition, and never claims OTA recovery.

## Bounds and orchestration

The runner allows four decision iterations, two retries after one Decider attempt, two connection retries total, one profile transition, one tool dispatch per decision, and one explanation call. Diagnostics loop after adding evidence. Retry/operator actions run both checks and loop only if budget remains. Profile timeout/failure is not command-retried. Escalation terminates. Bound exhaustion is a traced safe escalation except an unavailable required dependency, which is `DEPENDENCY_ERROR`. There is no recursion.

Behavior identity hashes only fixture revision, seed, approval, bounds/confidence policy, and simulator/action/gate versions. Endpoints, trace path, explainer type, lock/source/manifest metadata, and model references use a separate environment evidence hash, so changing an output path does not alter run/idempotency identity.

## Bedrock operation

`StrandsBedrockExplainer` uses `BedrockModel(region_name=..., model_id=profile_or_model, temperature=0.0, max_tokens=600)` with botocore 5-second connect, 60-second read, and standard two-attempt configuration. Its Agent has no tools. It receives sanitized observable state plus public tool/gate/check evidence only after dispatch. Prompt text labels the system simulated and forbids claims of real action. Output is bounded to 32 KiB and untrusted; it cannot alter target, gates, checks, or result.

`DeterministicLocalExplainer` formats a fixed terminal template; `LocalTestDoubleModel` exists solely to construct a Strands tool host without AWS. Neither reads credentials or opens network connections, and their invocation counters are independent. A spy proves Decider HTTP occurs, AWS calls do not, and inert host-model calls stay zero in local-double runs. Their output does not satisfy the hackathon's Bedrock qualification.

## Trace design

Use the strict common event envelope and complete event table in `architecture.md`. Causal IDs connect decision/model/effective values to one tool, profile tool to proposal, passing final gates to transition, and state-changing cause to two checks. `proposal_blocked` explicitly says no command. Duplicate suppression is distinct. Run start reports Decider, dispatch, explainer, simulator, and AWS statuses separately.

The recorder rejects impossible links and hidden canaries, buffers events, writes a sibling temporary file, fsyncs, and atomically renames. External raw JSON is preserved only after duplicate-safe schema/semantic validation. Wall time/duration are optional and excluded from deterministic comparisons.

## Concrete failure behavior

Input/fixture/manifest-path errors are caller-fixable but non-recoverable in-run: exit 2, ERROR, no dependencies. Manifest artifact/provenance or health mismatch is fatal dependency identity failure: exit 3, no question/tool. Decider connect/read/reset and 408/429/5xx retry twice at 0.25/0.50 seconds; exhaustion exits 3. Other 4xx, redirect, body over 64 KiB, duplicate/malformed JSON, probability/confidence/key/choice mismatch are non-retryable protocol failures and invoke no tool.

One-option escalation is a normal no-Decider path. Zero options, registry mismatch, evaluator leak, impossible transition, or Strands schema mismatch is an internal invariant failure: exit 4, CRITICAL. Unknown/stale tool requests are typed non-mutating domain rejection and can safely escalate. Gate denial is expected INFO and returns all final reasons plus blocked audit. Atomic-store failure commits nothing and exits 4. Simulated timeout/failure/check failure is a warning/domain result, never automatic duplicate command or rollback.

Bedrock SDK failure uses only configured attempts; it records unavailable but cannot undo simulation. A normal CLI run can finish with optional explanation unavailable; the enabled AWS integration test fails. Missing/denied approval is an expected INFO denial; binding mismatch, stale proposal basis, or consumed approval is also non-mutating and returns its stable gate reason. Trace/output finalization failure exits 4 and does not claim durable evidence. Exit 0 means a valid `RESTORED` or safe `ESCALATED` domain outcome, not necessarily recovery.

## Test strategy and acceptance

Unit-test schemas and fixture cross-fields, every occurrence effect, SHA outcomes, structural leakage/canaries, 0/1/2/24/25/255 filtering at capacity 24, model/effective policy, all six direct routes, stale/unknown/extra tool inputs, zero host-model calls, all gates, proposal-before-approval ordering, every approval-binding mismatch, preview/final race, successful atomic approval consumption, duplicate denied proposal, duplicate transition/dispatch, one-active-profile invariant, both checks, all bounds, IDs/hashes, event links, and error classification. Scripted loopback HTTP contract tests exercise the canonical client, connect/read failures, redirects, duplicate keys, malformed distributions, and 65,537-byte rejection. Default tests need no network, model, credentials, Docker, native ShellCheck, or cloud.

`real_decider` is skipped exactly unless opted in; once enabled, manifest/health/config failures fail. It remains label-agnostic and checks wire invariants plus actual-label-to-tool causality with confidence floor zero. A separate `production_path` marker is the semantic characterization gate: using the exact production BR projection/question, pinned service, default `0.20` policy, seed, bounded coordinator, and proposal-bound grant, it must observe profile evaluation, passing final gates, `ENABLED`, two passing layer checks, and `RESTORED`; it also runs exact `OFFLINE` and requires safe escalation with no transition. A changed real-model route fails characterization rather than skipping or substituting a fake. `aws_integration` repeats those same BR and OFFLINE production paths against the AWS host and makes one no-tools Bedrock call only after BR evidence exists; it never provisions. Exact commands and skip semantics are numbered in [`requirements.md`](requirements.md).

## AWS deployment artifacts

Implement the files and constraints in `docs/aws-deployment.md`. CloudFormation creates private interface endpoints for SSM/Logs/Bedrock and an S3 gateway endpoint, no public Decider or SSH, encrypted EBS, IMDSv2, and scoped roles; EC2 explicitly depends on endpoint and route resources. Interface endpoint DNS must resolve privately. S3 is instead validated by the private route table's regional prefix-list route to the exact gateway endpoint and an exact-version object request; public S3 DNS answers are not a failure. A separately built versioned archive contains lock-resolved wheels, app, pinned Decider source/adapter/base, notices, and an internal `files.manifest.json` listing every other normalized regular file while excluding itself. External operator/CloudFormation metadata supplies exact object version and archive SHA, avoiding a circular self-hash; adapter/base logical artifacts use explicit file sets or a defined Merkle root. Build and host validators share code and one round-trip test. Host bootstrap makes no PyPI/Hugging Face request. Every endpoint/artifact check is fatal before service readiness. `cfn-lint`, `bash -n`, and policy/manifest validation establish local reviewability only, not deployment; ShellCheck is optional.

## Review finding responses

Every blocking finding in [`design-review.md`](design-review.md) and `design-verdict.json` is addressed; none is backlogged or ignored:

1. **Exact real production slice:** retained the label-agnostic wire/causality test and added a separate opt-in `production_path` characterization using the exact BR projection, default `0.20` policy, pinned model, bounded runner, and proposal-bound grant. It must reach profile evaluation, five final passes, `ENABLED`, two passing checks, and `RESTORED`. AWS repeats this before Bedrock explanation, and real `OFFLINE` must create no transition.
2. **Concrete approval:** approval is created only after proposal trace and binds run, proposal, incident, source, target, and status; its deterministic ID includes those fields. Every mismatch/stale/consumed grant is denied and tested. Scripted CLI approval is labeled simulated intent.
3. **24-slot capacity:** trusted manifest/health supplies exact `num_slots=24`; the router permits HTTP only through that capacity and returns typed `UNSUPPORTED_CHOICE_CARDINALITY` locally for 25/255 without reduction, dispatch, or mutation. Boundary tests are explicit.
4. **S3 gateway verification:** private DNS checks now apply only to interface endpoints. S3 requires the expected endpoint ID on the regional prefix-list route plus exact-version object access. EC2 depends on endpoint/routes.
5. **Non-circular artifacts:** external metadata owns exact archive hash/version; internal `files.manifest.json` excludes itself and hashes every other normalized regular file. Logical adapter/base artifacts reference explicit files or a defined Merkle root, and shared production validators get a build/verify round-trip test.
6. **Structural truth isolation:** positive projections start from `ObservableIncident`; leakage bans evaluator keys/paths, hidden type/object serialization, private keys, and a unique non-overlapping canary. Public action/evidence enum values are allowed when independently produced by public schemas.
7. **Available lint toolchain:** pinned `cfn-lint` runs through `uv`; required shell validation is `bash -n`. ShellCheck is optional enhanced lint, so acceptance is reproducible on the observed host without an undocumented native bootstrap.

## Sources

Original specification: [`SIMShift_Project_Handoff.md`](../../../SIMShift_Project_Handoff.md). Submission rules: [`SIMShift_Hackathon_Requirements_and_Rules.md`](../../../SIMShift_Hackathon_Requirements_and_Rules.md). Observed environment: [`environment.md`](environment.md). Decider validation: [`decider-research.md`](decider-research.md). Strands/AWS validation: [`strands-aws-research.md`](strands-aws-research.md). Dev-tool release pins were checked against their PyPI project metadata on 2026-10-18; the committed lock and hash export are normative. Exact immutable external citations and access dates remain in the two research source ledgers.