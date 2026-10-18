# SIMShift — Open findings backlog (captured at loop end)

**Status:** The convergence (implement + semantic review) loop was ended by the user/orchestrator
after 5 fix-and-review passes. The vertical slice is functionally complete and all non-opt-in
quality gates pass; the real-Decider BR/OFFLINE path was exercised and retained. The latest
semantic review verdict was `CHANGES_REQUESTED` with the four items below still open. They are
captured here as a tracked follow-up backlog rather than resolved in this run.

Source review artifacts:
- `.agents/tasks/code-review.json` (machine-readable verdict)
- `.agents/tasks/code-review.md` (narrative review)

## Verified-good state at loop end (for context)

- Real Decider ran on CPU (no fake, no download fallback); opt-in `real_decider` + `production_path` tests passed.
- BR_PROFILE: real Decider chose `evaluate_profile_change` -> dispatched real Strands tool
  `prepare_guarded_profile_transition` -> all five gates -> virtual transition to `profile_B` ->
  registration + telemetry both verified -> terminal `RESTORED`.
- OFFLINE: forbidden remote actions filtered; real Decider chose `escalate_or_wait` ->
  `defer_or_escalate`; no transition; `profile_A` unchanged. Forced proposal blocked with
  `MANAGEMENT_UNREACHABLE`.
- Terminal gate-denial contract intact: `proposal_blocked` then `run_escalated(PROFILE_PROPOSAL_BLOCKED)`,
  no second Decider/tool/host-model/explainer call.
- Trace provenance separately labels `strands_framework_dispatch` (REAL),
  `strands_tool_host_model` (LOCAL_TEST_DOUBLE), `explainer_model` (LOCAL_TEST_DOUBLE).
- Gates at loop end: 121 passed, 3 opt-in skips; 40 pattern tests; ruff, mypy, license headers,
  shell syntax all clean. Six retained evidence SHA-256 hashes spot-checked and matched.
- AWS deployment and real Bedrock remain honestly UNVERIFIED; no Git/cloud/provisioning/publication occurred.

## Open findings (deferred follow-up)

### SIM-016 (MEDIUM) — Recovery evidence ordered after success in the BR trace
- **Where:** `src/simshift/orchestration/runner.py:_record_transition`;
  `src/simshift/tracing/events.py:validate_event_sequence`; `.agents/evidence/vertical-slice/br-profile.jsonl` seq 28-30.
- **Problem:** The in-memory engine computes both the registration and telemetry checks before
  deciding restoration, but the retained trace emits `VERIFYING -> SUCCEEDED` (seq 28) BEFORE the
  registration/telemetry check events (seq 29-30). The inspectable causal record therefore claims
  transition success before recording the evidence that establishes it, and `validate_event_sequence`
  currently accepts that ordering. Functionally correct, but the trace — the headline artifact —
  overstates when success became evidenced.
- **Fix:** Emit transition edges through `VERIFYING`, then the registration + telemetry check events,
  then the terminal `SUCCEEDED|FAILED` edge. Extend `validate_event_sequence` and the production-path
  tests to reject a terminal post-verification transition event unless both matching checks already precede it.

### SIM-017 (MEDIUM) — Canary truth-isolation backstop not wired into production sinks
- **Where:** `src/simshift/decision/projection.py:assert_no_evaluator_leak`;
  `src/simshift/tracing/events.py:TraceEvent.validate_event`; `src/simshift/tracing/recorder.py:TraceRecorder`;
  `src/simshift/integrations/bedrock.py`.
- **Problem:** `assert_no_evaluator_leak` only rejects canary text when the caller explicitly passes a
  canary tuple. Production `TraceEvent` validation, both explainers, and the CLI's
  `TraceRecorder(args.trace_out)` all use the empty default, so the advertised sink-level backstop is
  inactive in production. The normal typed path is still isolated (projections are positive allowlists;
  public DTOs carry no evaluator truth), but an `EVAL_ONLY_*` canary under an otherwise-allowed field
  would not be caught at the sink.
- **Fix:** Reject the reserved canary pattern intrinsically, OR propagate a non-secret fixture leak
  guard from fixture loading into every trace, tool/log, and explanation sink. Add sink-level tests
  using the normative fixture canaries (not literals supplied only to the assertion under test).

### SIM-018 (MEDIUM) — Standalone pattern client can emit duplicate JSON member names
- **Where:** `patterns/capability_aware_router/decider_client.py:DeciderClient.choose`.
- **Problem:** The reusable client validates only that `state` is `str`/`list`/`dict` before
  `json.dumps`. Python JSON encoding coerces non-string mapping keys, so distinct keys such as integer
  `1` and string `"1"` can serialize to duplicate outbound member names, contradicting the strict
  duplicate-free request contract. Matters because the reusable pattern is a hard hackathon requirement
  and must be robust for other builders.
- **Fix:** Recursively validate the public `JSONValue` contract before serialization — require string
  object keys and supported finite JSON values at every depth — and add a test proving ambiguous keys
  fail before any HTTP call.

### SIM-019 (LOW) — Approval provenance casing contradicts documented contract
- **Where:** `src/simshift/orchestration/runner.py:_handle_proposal` `approval_materialized` payload;
  `docs/architecture.md`; `docs/simulation-scope.md`; `.agents/tasks/requirements.md`.
- **Problem:** Runtime/evidence emit `source="scripted_simulated_intent"` while the documented exact
  provenance contract is `SCRIPTED_SIMULATED_INTENT`. `TraceEvent` leaves `source` unconstrained, so
  the claims/evidence drift is undetected.
- **Fix:** Emit the documented uppercase literal and constrain `approval_materialized.source` in the
  event schema and tests so future traces cannot drift.

## Recommended sequencing when this backlog is picked up

1. SIM-016 and SIM-017 first — both protect load-bearing submission claims (causal trace integrity and
   the truth-isolation invariant).
2. SIM-018 next — hardens the reusable pattern required by the hackathon.
3. SIM-019 — trivial literal/schema alignment.

After fixing, regenerate the real BR/OFFLINE traces, re-run the full non-opt-in gate set plus the
bounded real-Decider `real_decider`+`production_path` run, and refresh the evidence files.
