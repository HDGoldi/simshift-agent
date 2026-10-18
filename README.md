# SIMShift Agent

SIMShift is a Python 3.11 local-first vertical slice for capability-aware recovery routing. It combines a strict loopback Decider client, direct calls to six Strands-registered tools, deterministic synthetic telecom effects, guarded virtual profile transitions, and validated JSONL traces. The reusable domain-independent router is documented in [`patterns/capability_aware_router/README.md`](patterns/capability_aware_router/README.md).

## Evidence labels

- **REAL:** the retained loopback Decider run and direct Strands framework dispatch recorded under `.agents/evidence/vertical-slice/`.
- **LOCAL_TEST_DOUBLE:** the inert Strands tool-host model and default deterministic explainer; the host model is never invoked.
- **SIMULATED:** all telecom state, approvals, transitions, registration, telemetry, and outcomes.
- **OBSERVED:** the retained local Decider model, source, runtime lock, verified file manifest, provenance, and lossless hash-validated wire bodies under `.agents/evidence/decider` and `.agents/evidence/vertical-slice`. Retained base-model bytes are hash/Merkle verified, but their repository revision is explicitly inferred rather than independently proven.
- **UNVERIFIED:** AWS deployment, Bedrock account/model access, GPU behavior, cloud performance, and cost.

No real carrier, subscriber, modem, eUICC, SM-DP+, or cloud resource is contacted by default.

## Local development

```sh
uv sync --frozen --extra dev
uv run python -m simshift.cli validate-fixtures
uv run pytest -q
uv run pytest -q patterns/capability_aware_router/tests
uv run ruff check .
uv run mypy src patterns/capability_aware_router
uv run python scripts/check_license_headers.py
bash -n scripts/*.sh
```

The normal suite is offline. Opt-in tests skip with exact environment setup instructions.

## Real local Decider (opt-in)

The retained `decider-manifest.json` is the local trust anchor. Before any network call the adapter verifies its exact `files.manifest.json` hash, every listed regular-file size/hash, logical source/adapter/base Merkle roots, runtime lock, and model provenance bindings. Start the already-downloaded runtime in the foreground:

```sh
STRANDS_DECIDER_MODEL_DIR="$PWD/.agents/evidence/decider/model-v1-216d1ccb" \
STRANDS_DECIDER_PYTHON="$PWD/.agents/evidence/decider/runtime/venv/bin/python" \
HF_HOME="$PWD/.agents/evidence/decider/hf-cache" \
scripts/run-local-decider.sh
```

The launcher forces Hugging Face/Transformers offline mode and downloads nothing. In another terminal, run:

```sh
export STRANDS_DECIDER_URL=http://127.0.0.1:8099
export STRANDS_DECIDER_MANIFEST="$PWD/.agents/evidence/decider/decider-manifest.json"
SIMSHIFT_RUN_REAL_DECIDER=1 uv run pytest -q -m real_decider
SIMSHIFT_RUN_PRODUCTION_PATH=1 uv run pytest -q -m production_path
scripts/capture-local-evidence.sh
```

Once an opt-in is enabled, missing or mismatched configuration is a failure, not a skip. Evidence capture writes only results produced by the real endpoint and validates them; it never substitutes a fake.

## AWS status

AWS/Bedrock is optional, already-deployed-only, and **UNVERIFIED**. `SIMSHIFT_RUN_AWS_INTEGRATION=1` never provisions resources. Phase 2 hardening is tracked in [`infra/ec2/implementation-backlog.md`](infra/ec2/implementation-backlog.md); it is not a Phase 1 prerequisite.

This project is licensed under Apache-2.0.
