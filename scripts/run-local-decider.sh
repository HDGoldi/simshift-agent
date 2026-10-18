#!/bin/sh
# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0
set -eu

: "${STRANDS_DECIDER_MODEL_DIR:?set STRANDS_DECIDER_MODEL_DIR to the pinned local checkpoint}"
: "${STRANDS_DECIDER_PYTHON:?set STRANDS_DECIDER_PYTHON to the pinned Decider interpreter}"
: "${HF_HOME:?set HF_HOME to the existing offline Hugging Face cache}"

[ -x "$STRANDS_DECIDER_PYTHON" ] || {
  printf '%s\n' "STRANDS_DECIDER_PYTHON is not executable: $STRANDS_DECIDER_PYTHON" >&2
  exit 2
}
[ -d "$STRANDS_DECIDER_MODEL_DIR" ] || {
  printf '%s\n' "STRANDS_DECIDER_MODEL_DIR is not a directory: $STRANDS_DECIDER_MODEL_DIR" >&2
  exit 2
}
[ -d "$HF_HOME" ] || {
  printf '%s\n' "HF_HOME is not a directory: $HF_HOME" >&2
  exit 2
}

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(dirname -- "$SCRIPT_DIR")
DECIDER_SOURCE=${STRANDS_DECIDER_SOURCE:-"$PROJECT_ROOT/.agents/evidence/decider/repo/src"}
PORT=${STRANDS_DECIDER_PORT:-8099}

[ -d "$DECIDER_SOURCE/strands_decider" ] || {
  printf '%s\n' "Decider source package not found: $DECIDER_SOURCE/strands_decider" >&2
  exit 2
}

export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export PYTHONPATH="$DECIDER_SOURCE${PYTHONPATH:+:$PYTHONPATH}"
exec "$STRANDS_DECIDER_PYTHON" -m strands_decider.cli serve \
  "$STRANDS_DECIDER_MODEL_DIR" \
  --host 127.0.0.1 \
  --port "$PORT" \
  --device cpu \
  --model-name model-v1-216d1ccb \
  --strict-window
