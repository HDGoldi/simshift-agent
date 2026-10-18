#!/bin/sh
# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0
set -eu

: "${STRANDS_DECIDER_URL:?set STRANDS_DECIDER_URL to an already-running loopback service}"
: "${STRANDS_DECIDER_MANIFEST:?set STRANDS_DECIDER_MANIFEST to a trusted local manifest}"

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(dirname -- "$SCRIPT_DIR")
EVIDENCE_DIR="$PROJECT_ROOT/.agents/evidence/vertical-slice"
mkdir -p "$EVIDENCE_DIR"

cd "$PROJECT_ROOT"
uv run python -m simshift.cli run \
  --scenario BR_PROFILE --seed 20261018 --approval granted \
  --decider-url "$STRANDS_DECIDER_URL" \
  --decider-manifest "$STRANDS_DECIDER_MANIFEST" \
  --explainer local-test-double \
  --trace-out "$EVIDENCE_DIR/br-profile.jsonl"
uv run python -m simshift.cli run \
  --scenario OFFLINE --seed 20261019 --approval granted \
  --decider-url "$STRANDS_DECIDER_URL" \
  --decider-manifest "$STRANDS_DECIDER_MANIFEST" \
  --explainer local-test-double \
  --trace-out "$EVIDENCE_DIR/offline-run.jsonl"
uv run python -m simshift.cli policy-check \
  --scenario OFFLINE --seed 20261019 \
  --action evaluate_profile_change --approval granted \
  > "$EVIDENCE_DIR/offline-policy-check.json"
uv run python scripts/validate_trace.py \
  "$EVIDENCE_DIR/br-profile.jsonl" "$EVIDENCE_DIR/offline-run.jsonl" \
  "$EVIDENCE_DIR/offline-policy-check.json"
