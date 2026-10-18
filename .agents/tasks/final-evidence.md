# Final verification evidence

## Result

The complete non-opt-in quality gate passed, and the available real local Decider prerequisites were verified and exercised without a fake, download, cloud access, or deployment. However, the approved code review remains **CHANGES_REQUESTED**: all four approved findings (`SIM-016` through `SIM-019`) are still present in the verified tree. This evidence report does not claim product acceptance and does not change approved product behavior.

Every command below ran with `/projects/sandbox/simshift-agent` as cwd. No Git command or operation, cloud mutation, deployment, provisioning, publication, article creation, or video creation occurred.

## Complete non-opt-in quality gate

- `uv sync --frozen --extra dev` — **PASS**, exit 0: `Checked 59 packages in 0.55ms`.
- `uv run python -m simshift.cli validate-fixtures` — **PASS**, exit 0: `{"scenarios": ["BR_PROFILE", "OFFLINE"], "status": "VALID"}`.
- `uv run pytest -q` — **PASS**, exit 0: `121 passed, 3 skipped in 1.13s`.
- `uv run pytest -q patterns/capability_aware_router/tests` — **PASS**, exit 0: `40 passed in 0.18s`.
- `uv run ruff check .` — **PASS**, exit 0: `All checks passed!`.
- `uv run mypy src patterns/capability_aware_router` — **PASS**, exit 0: `Success: no issues found in 47 source files`.
- `uv run python scripts/check_license_headers.py` — **PASS**, exit 0: `license headers valid: 92 files`.
- `bash -n scripts/*.sh` — **PASS**, exit 0 with no output.
- `uv run python -m simshift.cli policy-check --scenario OFFLINE --seed 20261019 --action evaluate_profile_change --approval granted` — **PASS**, exit 0: `BLOCKED`, `MANAGEMENT_UNREACHABLE`, null transition, unchanged `profile_A` and state, approval unconsumed, and no command.

## Opt-in and real local Decider evidence

- `uv run pytest -q -m 'real_decider or production_path' -rs` without opt-in — **PASS with actionable skips**, exit 0: `2 skipped, 122 deselected in 0.54s`; exact reasons: `set SIMSHIFT_RUN_PRODUCTION_PATH=1` and `set SIMSHIFT_RUN_REAL_DECIDER=1`.
- `uv run pytest -q -m aws_integration -rs` — **PASS with actionable skip**, exit 0: `1 skipped, 123 deselected in 0.50s`; exact reason: `set SIMSHIFT_RUN_AWS_INTEGRATION=1`. It was not enabled because explicit AWS credentials and authorization were not supplied.
- `test -x .agents/evidence/decider/runtime/venv/bin/python && test -d .agents/evidence/decider/model-v1-216d1ccb && test -d .agents/evidence/decider/hf-cache && test -f .agents/evidence/decider/decider-manifest.json` — **PASS**, exit 0 with no output; every explicitly declared local Decider prerequisite was available.
- `PYTHONPATH=.agents/evidence/decider/repo/src HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .agents/evidence/decider/runtime/venv/bin/python -m strands_decider.hf_export verify .agents/evidence/decider/model-v1-216d1ccb` — **PASS**, exit 0: `.agents/evidence/decider/model-v1-216d1ccb: ok`.
- The bounded command below — **PASS**, exit 0: real opt-in tests reported `2 passed, 122 deselected in 18.52s`; capture reported BR `RESTORED/PROFILE_TRANSITION_VERIFIED` on `profile_B`, OFFLINE `ESCALATED/SAFE_TOOL_ESCALATION` on unchanged `profile_A`, and `validated real Decider BR/OFFLINE evidence`.

```sh
set -eu; STRANDS_DECIDER_MODEL_DIR=/projects/sandbox/simshift-agent/.agents/evidence/decider/model-v1-216d1ccb STRANDS_DECIDER_PYTHON=/projects/sandbox/simshift-agent/.agents/evidence/decider/runtime/venv/bin/python HF_HOME=/projects/sandbox/simshift-agent/.agents/evidence/decider/hf-cache STRANDS_DECIDER_PORT=8099 scripts/run-local-decider.sh & pid=$!; trap 'kill "$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true' EXIT; ready=0; for i in $(seq 1 300); do if uv run python -c 'from patterns.capability_aware_router.decider_client import DeciderClient; DeciderClient("http://127.0.0.1:8099", connect_timeout=1, read_timeout=2).health()' 2>/dev/null; then ready=1; break; fi; sleep 1; done; [ "$ready" -eq 1 ]; SIMSHIFT_RUN_REAL_DECIDER=1 SIMSHIFT_RUN_PRODUCTION_PATH=1 STRANDS_DECIDER_URL=http://127.0.0.1:8099 STRANDS_DECIDER_MANIFEST=/projects/sandbox/simshift-agent/.agents/evidence/decider/decider-manifest.json uv run pytest -q -m 'real_decider or production_path' -rs; STRANDS_DECIDER_URL=http://127.0.0.1:8099 STRANDS_DECIDER_MANIFEST=/projects/sandbox/simshift-agent/.agents/evidence/decider/decider-manifest.json scripts/capture-local-evidence.sh
```

- `uv run python scripts/validate_trace.py .agents/evidence/vertical-slice/br-profile.jsonl .agents/evidence/vertical-slice/offline-run.jsonl .agents/evidence/vertical-slice/offline-policy-check.json` — **PASS**, exit 0: `validated real Decider BR/OFFLINE evidence`. This validator success does **not** close `SIM-016`; it currently accepts the reversed terminal/check order.
- `sha256sum .agents/evidence/vertical-slice/br-profile.jsonl .agents/evidence/vertical-slice/offline-run.jsonl .agents/evidence/vertical-slice/offline-policy-check.json uv.lock .agents/evidence/decider/decider-manifest.json .agents/evidence/decider/files.manifest.json` — **PASS**, exit 0; hashes are listed below.
- `uv run python -c 'import json; from pathlib import Path; paths=[Path(".agents/evidence/vertical-slice/br-profile.jsonl"),Path(".agents/evidence/vertical-slice/offline-run.jsonl")];\nfor path in paths:\n events=[json.loads(line) for line in path.read_text().splitlines()]; start=events[0]["payload"]; req=next(e["payload"] for e in events if e["event_type"]=="decider_request"); response=next(e["payload"] for e in events if e["event_type"]=="decider_response"); print(path, start["environment_evidence_hash"], req["request_hash"], response["model_choice"])'` — **PASS**, exit 0; values are listed below.
- `uv run python -c 'import json; from pathlib import Path; p=Path(".agents/evidence/vertical-slice/br-profile.jsonl"); events=[json.loads(x) for x in p.read_text().splitlines()];\nfor e in events:\n if e["event_type"] in {"transition_state_changed","registration_check_completed","telemetry_check_completed","approval_materialized"}: print(e["sequence"],e["event_type"],e["payload"])'` — **PASS**, exit 0; it printed sequence 10 and confirmed `approval_materialized.source="scripted_simulated_intent"`. Direct trace inspection separately confirms sequences 28–30 for `SIM-016`.

- `uv run python -m json.tool .agents/tasks/verification-results.json >/dev/null` — **PASS**, exit 0 with no output.
- `test -s .agents/tasks/final-evidence.md && test -s .agents/tasks/verification-results.json` — **PASS**, exit 0 with no output.

## Retained evidence and hashes

- `.agents/evidence/vertical-slice/br-profile.jsonl` — **OBSERVED real-local-Decider output; validator accepted with known review inaccuracies**, SHA-256 `7e4776d39ee48b0d4b1f91cf396993cfc91d53973a35f38aed4577886dc013e6`; environment evidence hash `e84a35a2e982935ad766796035b7d848658c70f74aae865179ad8838aa5e736b`; request hash `b8645137f2fdb9039a7c00687197d5d6d71830204f26629cd52f74dac98a377a`; actual model choice `evaluate_profile_change`; matching tool `prepare_guarded_profile_transition`; final status `RESTORED` on `profile_B`.
- `.agents/evidence/vertical-slice/offline-run.jsonl` — **OBSERVED and VALIDATED**, SHA-256 `414a3ff240b311714e1d6d69ea804d35368600a52fe758f96e63d0dd363664bb`; environment evidence hash `e84a35a2e982935ad766796035b7d848658c70f74aae865179ad8838aa5e736b`; request hash `cb826b405e6dd0a91cdf8c4613100be1ef4d0608bdb98f44f89926cb4279ce40`; actual model choice `escalate_or_wait`; matching tool `defer_or_escalate`; no transition lifecycle; unchanged `profile_A`.
- `.agents/evidence/vertical-slice/offline-policy-check.json` — **OBSERVED and VALIDATED**, SHA-256 `f35cfeb2e9b78efdff0441f7868b68e41d36fb7881574e30b026ea2d8ea41775`.
- `uv.lock` — SHA-256 `12def5766be3ee5947e6cf3773bd32fe86481229c8f5c8c423c5c958db6b5190`.
- `.agents/evidence/decider/decider-manifest.json` — SHA-256 `146ce9b86bf671a4d577036e390a940e88461984b8a71040f0de285227426156`.
- `.agents/evidence/decider/files.manifest.json` — SHA-256 `1814b697efce120356087f7a2f4d313d715b1c2b9f03f66f7884cf91b82a5a10`.
- The model export is content-verified. Its declared base Hub revision remains **INFERRED / NOT INDEPENDENTLY VERIFIED**.

## Approved review findings still open

- **SIM-016 — open:** retained BR sequence 28 is `transition_changed` from `VERIFYING` to `SUCCEEDED`; passing `registration_check` and `telemetry_check` occur afterward at sequences 29 and 30. `validate_trace.py` nevertheless exits 0. The trace therefore must not be described as having evidenced success before the two checks.
- **SIM-017 — open:** `assert_no_evaluator_leak` only rejects fixture canaries supplied through its optional `canaries` argument. `TraceEvent.validate_event` and explainer paths call it without canaries, and `TraceRecorder` defaults to an empty tuple. Production sinks therefore do not enforce the claimed intrinsic `EVAL_ONLY_*` backstop.
- **SIM-018 — open:** `DeciderClient.choose` validates only that `state` is a string, list, or dict before `json.dumps`; it does not recursively require string mapping keys. Ambiguous keys such as integer `1` and string `"1"` can still be serialized to duplicate outbound JSON member names.
- **SIM-019 — open:** retained BR sequence 10 has `approval_materialized.source="scripted_simulated_intent"`, not the documented exact `SCRIPTED_SIMULATED_INTENT`; the event schema does not constrain the value.

## Evidence labels and claim boundaries

- **REAL:** the pinned local loopback Decider service and its observed HTTP choices; direct Strands framework registered-tool dispatch.
- **LOCAL_TEST_DOUBLE:** the inert Strands tool-host model (observed uninvoked) and deterministic local explainer.
- **SIMULATED:** telecom fleet/eUICC effects, registration and telemetry outcomes, profile approval intent, policy gates, and incident orchestration. No real telecom action occurred.
- **UNVERIFIED:** AWS deployment, real Amazon Bedrock invocation, GPU behavior, real telecom integration, cloud OFFLINE characterization, accuracy, performance, cost, and production readiness. The base Hub revision is inferred rather than independently verified.

## Deferred Phase 2 AWS work

Phase 2 remains documentation/backlog only and non-blocking for the local slice: hardened Hugging Face cache/offline mode; stage-zero and AMI contracts; EC2 describe-only IAM characterization; private endpoints; offline bundle and Merkle validation; and normative cloud OFFLINE characterization. No CloudFormation or deployable infrastructure artifact is claimed complete. No AWS test was enabled, and no cloud service was contacted or mutated.

## Prohibited-action confirmation

No Git initialization, commit, push, pull request, or other Git action occurred. No AWS/cloud mutation, deployment, provisioning, upload, publication, article, or video action occurred. Only local dependency verification, local tests/static checks, a bounded literal-loopback Decider process, local trace capture, and these two evidence-file updates were performed.
