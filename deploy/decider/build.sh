#!/usr/bin/env bash
# Stage the build context (pinned Decider source + both model snapshots) and build the arm64 image.
#   deploy/decider/build.sh [image-tag]
set -euo pipefail
DECIDER_SRC=${DECIDER_SRC:-$HOME/_Projects/strands-decider}
DECIDER_REV=930e6d5d
HUB=${HF_HUB_CACHE:-$HOME/.cache/huggingface/hub}
ADAPTER=$HUB/models--StrandsAgents--strands-decider-2B-qwen3.5-v1-2610/snapshots/216d1ccb46a9e9b036eb9187b248db98480f77d4
BASE=models--Qwen--Qwen3.5-2B-Base/snapshots/b1485b2fa6dfa1287294f269f5fb618e03d52d7c
TAG=${1:-simshift-decider:latest}

CTX=$(mktemp -d)
trap 'rm -rf "$CTX"' EXIT
mkdir -p "$CTX/src" "$CTX/models/decider" "$CTX/models/hub/$BASE"
git -C "$DECIDER_SRC" archive "$DECIDER_REV" | tar -x -C "$CTX/src"
cp -RL "$ADAPTER/." "$CTX/models/decider/"
cp -RL "$HUB/$BASE/." "$CTX/models/hub/$BASE/"
docker build --platform linux/arm64 -f "$(dirname "$0")/Dockerfile" -t "$TAG" "$CTX"
