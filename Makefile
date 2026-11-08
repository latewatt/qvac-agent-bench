PY ?= .venv/bin/python
MODELS ?= qwen3.5-0.8b,qwen3.5-2b,qwen3.5-4b,qwen3.5-9b
VERSIONS ?= 0.20.1,0.21.0,0.21.1,0.22.0,0.23.0
HARNESS ?= ../small-model-harness
MODEL ?= qwen3.5-4b

.PHONY: setup install-qvac test toolcalls smoke report config serve coding

setup:
	python3 -m venv .venv
	$(PY) -m pip install -q -e '.[dev]'

install-qvac:            ## pinned @qvac/cli + @qvac/sdk under qvac/node_modules
	cd qvac && npm ci --no-audit --no-fund

test:                    ## offline: scoring, config, server log parsing, report
	$(PY) -m pytest -q

toolcalls:               ## start qvac serve, run the suite for each model in MODELS
	$(PY) -m qvac_bench.cli toolcalls --models $(MODELS)

smoke:                   ## fresh-install each SDK version and round-trip a heartbeat
	$(PY) -m qvac_bench.cli smoke --versions $(VERSIONS)

report:
	$(PY) -m qvac_bench.cli report

config:
	$(PY) -m qvac_bench.cli config --models $(MODELS)

serve:                   ## keep qvac serve running on :11460 (for make coding or other clients)
	$(PY) -m qvac_bench.cli serve --models $(MODEL)

coding:                  ## run the small-model-harness coding suite against `make serve MODEL=...`
	$(MAKE) -C $(HARNESS) bench BASE_URL=http://127.0.0.1:11460/v1 MODEL=$(MODEL) AGENT=baseline SUBSET=mini10 TASK_TIMEOUT=600
