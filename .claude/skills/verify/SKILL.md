---
name: verify
description: Build/launch/drive recipe for verifying SIMShift changes at the CLI, web UI and orchestrator surfaces.
---

# Verifying SIMShift

Setup: `make install`. Live runs need the Decider server on :8099 (`lsof -iTCP:8099 -sTCP:LISTEN`; start command in
README "Live" section) and, for Bedrock, `AWS_PROFILE=<your-profile>`.

## Surfaces and flows worth driving

- **Replay (no Decider, no AWS):** `env -i PATH=/usr/bin:/bin HOME=$(mktemp -d) DECIDER_URL=http://127.0.0.1:1 make replay`.
  Plain-loop traces: `python -m simshift.agent <S> --approve --no-bedrock --replay docs/sample-runs/<S>.json`.
- **CLI approval prompt:** needs a tty. Use an isolated tmux: `tmux -L verify new-session -d -s v ...`, wait for `y/N`,
  then `send-keys`. With `</dev/null` and no `--approve` the proposal stays pending.
- **Validator:** `python -m simshift.validate <trace.json>`; tamper a copy (flip `trace[i].decision.raw.choice`) to see FAIL.
- **Web UI:** `python -m simshift.web --port 8191` (live Decider) or `--replay-dir docs/sample-runs/orchestrated`.
  Incident ids start at **1**. POSTs need `content-type: application/json`. Probe `{"approved":"false"}` (400),
  foreign `origin` (403), foreign `host` (403), step while pending (409).
  Browser: chrome-devtools `new_page` with `isolatedContext`; screenshots cannot be saved to /tmp (outside workspace roots).
- **Orchestrator (Bedrock, ~7 s):** `python -m simshift.orchestrator TRANSIENT --out /tmp/x.json`, then validate it.

## Gotchas

- `--no-bedrock` runs (including `make replay`) and the validator ignore `AWS_PROFILE`; `--replay` without `--no-bedrock`
  still builds a `BedrockModel`. `make test` needs `AWS_PROFILE` unset or valid: the pattern tests and the
  Bedrock-mocked agent tests construct a `BedrockModel`.
- Benchmark runs take ~20-40 min with both Bedrock choosers; run them in the background.
