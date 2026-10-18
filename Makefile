PY      ?= .venv/bin/python
MODEL   ?= StrandsAgents/strands-decider-2B-qwen3.5-v1-2610
REV     ?= 216d1ccb46a9e9b036eb9187b248db98480f77d4
DEVICE  ?= cpu
PORT    ?= 8099

.PHONY: venv install install-decider serve-decider test test-live run ui ui-fake bench bench-fast example lint

venv:
	uv venv --python 3.12 .venv

install: venv
	uv pip install --python $(PY) -e ".[agent,dev]"

# CPU-only torch first, so pip does not pull CUDA wheels on a GPU-less Linux box.
install-decider:
	uv pip install --python $(PY) "torch==2.7.1" --index-url https://download.pytorch.org/whl/cpu
	uv pip install --python $(PY) -e ".[decider-server]"

# Binds to localhost only. The server has no authentication.
serve-decider:
	.venv/bin/strands-decider serve $(MODEL) --device $(DEVICE) --host 127.0.0.1 --port $(PORT)

test:
	$(PY) -m pytest -q -m "not live"

test-live:
	$(PY) -m pytest -q -m live

run:
	$(PY) -m agent.main

# Decision-trace UI on http://127.0.0.1:8090 (localhost only, no auth). Needs serve-decider running.
ui:
	$(PY) -m web.server --port 8090

ui-fake:
	$(PY) -m web.server --port 8090 --fake-decider

# Benchmark on the held-out split. `decider` needs serve-decider; `bedrock` needs Bedrock access.
bench:
	$(PY) -m evaluation.benchmark --strategies rules,random,decider

bench-fast:
	$(PY) -m evaluation.benchmark --strategies rules,random

example:
	$(PY) -m patterns.capability_aware_router.example

lint:
	$(PY) -m ruff check .
