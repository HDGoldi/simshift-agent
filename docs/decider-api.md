# Decider API contract for SIMShift

## Status and immutable pins

- **VERIFIED:** canonical source `strands-labs/strands-decider` at commit [`930e6d5de16309be32579f5631a7369a3322140c`](https://github.com/strands-labs/strands-decider/tree/930e6d5de16309be32579f5631a7369a3322140c).
- **VERIFIED:** checkpoint `StrandsAgents/strands-decider-2B-qwen3.5-v1-2610` at [`216d1ccb46a9e9b036eb9187b248db98480f77d4`](https://huggingface.co/StrandsAgents/strands-decider-2B-qwen3.5-v1-2610/tree/216d1ccb46a9e9b036eb9187b248db98480f77d4). The retained base-model bytes are hash/Merkle verified, but their declared `Qwen/Qwen3.5-2B-Base` revision `b1485b2fa6dfa1287294f269f5fb618e03d52d7c` is **INFERRED**, because the training hosts did not pin it; no independent immutable repository index binds those bytes to that commit.
- **OBSERVED:** the real pinned CPU service was invoked through `SimshiftDeciderAdapter`, `DecisionCoordinator`, and direct Strands dispatch. Retained BR evidence selected `evaluate_profile_change`; retained OFFLINE evidence selected `escalate_or_wait`. Exact probabilities, health, request/response payloads, tool names, and validated traces are under [`.agents/evidence/vertical-slice/`](../.agents/evidence/vertical-slice/).
- **IMPLEMENTED:** the canonical strict client, SIMShift adapter, opt-in real/production-path tests, foreground launcher, and evidence validator. **UNVERIFIED:** AWS hosting, GPU, authentication wrapper, domain quality, and confidence calibration.

These facts and exact source symbols are documented in [`.agents/tasks/decider-research.md`](../.agents/tasks/decider-research.md).

## One canonical client and adapter boundary

`patterns/capability_aware_router/decider_client.py` is the independent canonical implementation of URL parsing, `http.client` transport, request serialization, duplicate-safe JSON decoding, body cap, response schema/probability/confidence validation, and basic one-attempt `GET`/`POST`. It depends on no telecom module.

`src/simshift/integrations/decider_http.py` imports that client. Its `SimshiftDeciderAdapter` adds only observable projection, trusted deployment-manifest verification, exact health consistency policy, retries, SIMShift trace/log fields, and conversion to domain DTOs. It must not reimplement JSON or answer validation. The CLI, portable non-telecom example, contract tests, and real integration tests therefore exercise the same parser/transport; the example may use the canonical client directly while SIMShift uses the wrapper.

There is no production fake. Unit fakes live under `tests/fakes/`.

## Endpoint and transport contract

The MVP is same-host only. Accept exactly these origins:

```text
http://127.0.0.1:<1..65535>
http://[::1]:<1..65535>
```

An empty path or `/` is normalized away. Reject DNS hostnames (including `localhost`), non-loopback literals, HTTPS, userinfo, query, fragment, custom path, missing/zero port, and whitespace/control characters. The client appends exact `/health` and `/v1/systemone`. It does not follow redirects; every 3xx is a non-retryable protocol error. This avoids DNS rebinding and reflects the chosen same-EC2-host architecture. There is no `--allow-private-decider-host` flag in this slice.

Use `http.client.HTTPConnection`. Set connection timeout to 2.0 seconds, call `connect()`, then set `connection.sock.settimeout(30.0)` before request/response reading. Send `Accept: application/json`, and for POST `Content-Type: application/json; charset=utf-8` plus exact `Content-Length`. `Connection: close` is used so retry attempts do not reuse uncertain sockets.

If `Content-Length > 65536`, reject before reading. Otherwise read at most 65,537 bytes using bounded chunks; reject when the 65,537th byte exists. A missing/chunked length remains bounded by the same read. Close in `finally`. Decode strict UTF-8. Decode JSON with an `object_pairs_hook` that raises on a duplicate key at **any depth**; this applies to health and decision responses. Reject NaN/Infinity and non-object top-level bodies. Duplicate/malformed JSON is a non-retryable protocol error and no interpreted/raw validated payload is traced.

The wrapper permits two retries after the initial attempt, delays 0.25 and 0.50 seconds, and retries only connect/read timeout, connection reset/refused/EOF before a complete response, HTTP 408, 429, and 500–599. Retry does not apply to DNS (none is used), 3xx, other 4xx, duplicate/malformed JSON, size/schema/semantic errors, or manifest/health mismatch. After exhaustion return `DEPENDENCY_ERROR`, log ERROR, and dispatch no tool.

## Trusted deployment manifest and health consistency

A real run requires `--decider-manifest` / `STRANDS_DECIDER_MANIFEST`, a local root/operator-supplied JSON file parsed duplicate-safely. This deployment manifest references files from the separately verified internal bundle file manifest; it never assigns a digest to an unordered directory:

```json
{
  "schema_version": "1.1",
  "source": {"repository":"https://github.com/strands-labs/strands-decider","commit":"930e6d5de16309be32579f5631a7369a3322140c"},
  "checkpoint": {"repository":"StrandsAgents/strands-decider-2B-qwen3.5-v1-2610","commit":"216d1ccb46a9e9b036eb9187b248db98480f77d4"},
  "base": {"repository":"Qwen/Qwen3.5-2B-Base","commit":"b1485b2fa6dfa1287294f269f5fb618e03d52d7c"},
  "expected_health": {
    "model":"model-v1-216d1ccb",
    "checkpoint":"/opt/simshift/models/strands-decider-2B-qwen3.5-v1-2610-216d1ccb",
    "base_model":"Qwen/Qwen3.5-2B-Base",
    "device":"cpu", "max_length":4096, "num_slots":24, "vision":false
  },
  "file_manifest_path":"files.manifest.json",
  "file_manifest_sha256":"<sha256 of exact files.manifest.json bytes>",
  "provenance_path":"model/provenance.json",
  "logical_artifacts": [
    {"logical_name":"source_snapshot","merkle_root":"<64 lowercase hex>","paths":["source/strands_decider/schema.py","source/strands_decider/server.py"]},
    {"logical_name":"adapter_snapshot","merkle_root":"<64 lowercase hex>","paths":["models/adapter/adapter_config.json","models/adapter/adapter_model.safetensors"]},
    {"logical_name":"base_snapshot","merkle_root":"<64 lowercase hex>","paths":["models/base/config.json","models/base/model.safetensors"]},
    {"logical_name":"model_provenance","paths":["model/provenance.json"]},
    {"logical_name":"dependency_lock","paths":["locks/linux-cpu.txt"]}
  ]
}
```

The shown path list is illustrative; generated manifests enumerate every actual regular file. Paths are normalized UTF-8 POSIX relative paths, sorted by UTF-8 bytes, with no empty/`.`/`..`, absolute, duplicate, backslash, symlink, device, or hardlink entry. For a logical artifact, leaf bytes are `UTF8(path) + NUL + decimal_size + NUL + raw_sha256_bytes`; `merkle_root` is SHA-256 of the concatenated leaf hashes in sorted order. Single-file artifacts may omit a Merkle root and use the exact file's manifest hash. Every referenced path must exist in internal `files.manifest.json`; unreferenced regular files are still verified by that manifest.

Before service startup, deployment tooling verifies the externally supplied archive SHA/version, extracts safely, verifies every file in `files.manifest.json`, and runs `python -m strands_decider.hf_export verify`; it preserves the provenance file's explicitly inferred base-revision declaration without treating that declaration as independent repository proof. Before a local integration run, SIMShift verifies the same retained-byte chain: normalized non-symlink regular paths under the manifest root, exact size/SHA-256 for every listed file, source/adapter/base Merkle roots, the runtime lock, and provenance bindings for the inferred base-revision label plus adapter/head/config/train digests. The retained local trust anchor is [`.agents/evidence/decider/decider-manifest.json`](../.agents/evidence/decider/decider-manifest.json); its internal file manifest is separately hashed by that anchor.

Call `GET /health` once per adapter process after manifest verification. Require exact `status="ok"`, manifest `model`, `checkpoint`, `base_model`, `device`, `max_length=4096`, `vision=false`, and `num_slots=24`; `prefix_cache` is required and recorded but not policy-constrained. Unknown bounded fields are retained as extensions. A mismatch is fatal before `/v1/systemone`. The upstream model/path strings are mutable startup labels, so matching health is only endpoint consistency evidence—not cryptographic attestation. Artifact trust comes from the separately verified manifest chain and deployment custody.

## Exact choice request

The verified upstream request is `POST /v1/systemone`. `state` is `string|object|array`; `questions` is non-empty; optional `model` does not route the server checkpoint; images require vision. SIMShift sends structured object state, exactly one `choice`, no images, and omits `model`.

```json
{
  "state": {
    "schema_version":"1.0", "incident_id":"BR_PROFILE",
    "observation_revision":0, "country_code":"BR", "cohort_size":3200,
    "registration_status":"FAILED", "attach_success_rate":0.04,
    "telemetry_status":"MISSING", "telemetry_ack_rate":0.0,
    "active_profile_id":"profile_A", "alternative_profile_installed":true,
    "allowed_alternative_operator_available":false,
    "management_reachability":"REACHABLE", "ipa_available":true,
    "eim_associated":true, "recent_firmware_change":false,
    "connection_retry_count":0, "transition_count":0,
    "action_counts":{"retry_connection":0,"try_allowed_operator":0,"investigate_device":0,"investigate_data_path":0,"evaluate_profile_change":0,"escalate_or_wait":0},
    "evidence":["PERSISTENT_ATTACH_FAILURES","ALT_PROFILE_INVENTORY_CONFIRMED","NO_ALLOWED_ALTERNATE_OPERATOR","BOOTSTRAP_CHANNEL_REACHABLE"]
  },
  "questions": {
    "next_recovery_step": {
      "type":"choice",
      "instructions":"Given the current cellular connectivity symptoms, existing diagnostic evidence, and admissible tools, which next tool is most useful for safely advancing service restoration? Choose one listed tool. Profile evaluation neither authorizes nor executes a profile change.",
      "criteria": {
        "retry_connection":"Run one bounded simulated retry on the active subscription.",
        "investigate_device":"Read synthetic modem and device diagnostics.",
        "evaluate_profile_change":"Prepare a feasibility proposal only; do not enable a profile.",
        "escalate_or_wait":"Stop automated recovery and record safe escalation."
      }
    }
  }
}
```

`criteria` contains exactly the filtered options in registry order. The upstream schema permits 2–255 criteria, but this pinned checkpoint exposes only 24 slots. The router therefore requires `2 <= len(criteria) <= min(255, trusted_num_slots)` and, for this manifest, exact capacity 24. Counts 0/1 return `INSUFFICIENT_CHOICE_CARDINALITY`; 25–255 return `UNSUPPORTED_CHOICE_CARDINALITY`; both occur before HTTP and dispatch, with no silent option reduction. Label regex is `^[a-z][a-z0-9_]{0,63}$`; descriptions are 1–300 UTF-8 characters; instructions 1–1,000; serialized state at most 24 KiB; complete request at most 32 KiB. External input cannot supply text/options. The upstream server runs `--strict-window`; HTTP 422 for window overflow is non-retryable.

Projection accepts only `ObservableIncident` and constructs a new allowlisted object. It never deletes fields from a raw fixture. Recursive sink validation rejects evaluator-only keys/paths (`hidden_truth`, `_evaluator_truth`, `hidden_cause`, `true_cause`, `acceptable_next_actions`, `expected_route`, `expected_outcome`, `effects`, rewards, and private `_` keys), `HiddenCause`, serialized `EvaluatorTruth`/`ActionEffect`, and the fixture's unique non-overlapping `EVAL_ONLY_*` canary. Public action/evidence values are allowed when independently emitted by public DTOs. The same structural exclusion applies to Bedrock, tools, trace, and logs.

## Exact response and validation

```json
{
  "model":"model-v1-216d1ccb",
  "answers": {
    "next_recovery_step": {
      "type":"choice", "choice":"evaluate_profile_change",
      "probabilities":{"retry_connection":0.3026,"investigate_device":0.0795,"evaluate_profile_change":0.4841,"escalate_or_wait":0.1337},
      "confidence":0.3122
    }
  },
  "usage":{"input_tokens":354,"output_tokens":1},
  "latency_ms":6755.44
}
```

`latency_ms` is an optional HTTP implementation extension absent from the declared Pydantic/OpenAPI response. Unknown top-level fields are retained only in a recursively bounded `extensions` map (max 16 keys/depth 4/scalar string 1,000 chars) and never influence routing.

Require non-empty model equal to manifest expected-health model; exactly requested answer key; type `choice`; choice in submitted options and local registry; probability keys exactly submitted keys; each finite `[0,1]`; sum within `0.002` of one; chosen value maximal allowing a four-decimal tie; confidence finite `[0,1]` and within `0.002` of `(N*p_max-1)/(N-1)`; usage non-negative integers; optional latency finite/non-negative. Booleans are rejected where integers are expected. Failure is non-retryable and dispatches no tool.

The DTO names the returned value `model_choice`. Decision policy subsequently creates `effective_choice`. Under default floor `0.20`, a lower valid confidence keeps the raw/model choice in evidence but sets effective choice to `escalate_or_wait`, reason `LOW_CONFIDENCE`. This is a conservative orchestration policy, not part of Decider validation and not calibrated. The causal integration test sets `DecisionPolicy(min_confidence=0)` so any valid real returned label invokes its exact matching safe/proposal-only tool; a separate unit test verifies override behavior.

## Errors and caller results

- Manifest/path/config invalid: caller receives `ConfigurationError`; exit 2 before network.
- Manifest hash/provenance or health mismatch: `DependencyIdentityError`; exit 3, ERROR, no question/tool.
- Retryable transport/status: per-attempt warning event; final `DeciderUnavailable`; exit 3.
- Redirect, non-retryable HTTP, over-limit, duplicate/malformed JSON, schema/formula/key/choice mismatch: `DeciderProtocolError`; exit 3, no retry/tool.
- Valid response: caller receives immutable `ChoiceDecision` containing model choice, exact probabilities, confidence, usage, optional server latency, measured client latency, and bounded extensions.

## Integration-test contract

Default tests use scripted test-only clients/servers and make no external connection. Tests marked `real_decider` run only when `SIMSHIFT_RUN_REAL_DECIDER=1`; otherwise `pytest.skip("set SIMSHIFT_RUN_REAL_DECIDER=1")`. Once enabled, missing URL/manifest/model directory, file-manifest/hash/provenance failure, health mismatch including `num_slots != 24`, connection failure, or malformed output is a **failure**, never a skip. Tests never download weights. The label-agnostic wire/causality test uses confidence floor zero, asserts only response invariants, and proves exactly the returned label's tool ran.

Tests marked `production_path` run only when `SIMSHIFT_RUN_PRODUCTION_PATH=1`; otherwise they skip exactly `set SIMSHIFT_RUN_PRODUCTION_PATH=1`. Once enabled, they run the actual bounded production coordinator—not a hand-built request—with the exact request in this document, BR seed `20261018`, default confidence floor `0.20`, and scripted simulated approval materialized after and bound to the proposal. The pinned real model must cause a traced `evaluate_profile_change` dispatch, five passing final gates, `ENABLED`, distinct passing registration and telemetry checks, `SUCCEEDED`, and `RESTORED`. The same marker runs exact `OFFLINE` seed `20261019`; its real-model path must safely escalate without any transition record/lifecycle event, approval consumption, or active-profile change. A different semantic route is a characterization failure requiring prompt/fixture review, not a reason to skip, lower the policy, or substitute a fake.

A local-model fixture requires an already downloaded `STRANDS_DECIDER_MODEL_DIR`, verifies it, starts one strict-window loopback worker, waits for matching health, and terminates it in fixture finalization. A pre-running service requires its trusted manifest/evidence path. Lossless bounded UTF-8 health/request/response bodies, their SHA-256 digests, decoded semantic projections, and complete causal traces are retained as evidence. Trace loading recomputes both request/response hashes, duplicate-safely decodes the exact retained bytes, and compares response choice/probability/confidence/usage fields before accepting the evidence. Expected labels are asserted only by the separate production characterization, never by the generic protocol test.

## Sources

Verified schema/formulas: [`schema.py`](https://github.com/strands-labs/strands-decider/blob/930e6d5de16309be32579f5631a7369a3322140c/src/strands_decider/schema.py). HTTP/health: [`server.py`](https://github.com/strands-labs/strands-decider/blob/930e6d5de16309be32579f5631a7369a3322140c/src/strands_decider/server.py). Engine: [`infer.py`](https://github.com/strands-labs/strands-decider/blob/930e6d5de16309be32579f5631a7369a3322140c/src/strands_decider/infer.py). Full validation/evidence: [`.agents/tasks/decider-research.md`](../.agents/tasks/decider-research.md).