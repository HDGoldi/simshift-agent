# Convenience targets. Everything here also works as the plain command shown in the README.
PY := .venv/bin/python

install:
	uv venv && uv pip install -e . pytest

test:
	.venv/bin/pytest -q
	$(PY) -m simshift.validate docs/sample-runs/*.json docs/sample-runs/orchestrated/*.json

replay:  # re-run every published trace against the recorded Decider answers (no Decider server, no AWS)
	for f in docs/sample-runs/orchestrated/*.json; do s=$$(basename $$f .json); \
	  $(PY) -m simshift.agent $$s --approve --no-bedrock --replay $$f | grep -E "^===|route=|^outcome"; done

ui:  # recorded real Decider answers; open http://127.0.0.1:8090
	$(PY) -m simshift.web --replay-dir docs/sample-runs/orchestrated

ui-live:  # needs the Decider server on :8099 and AWS credentials for Bedrock
	$(PY) -m simshift.web --bedrock

.PHONY: install test replay ui ui-live
