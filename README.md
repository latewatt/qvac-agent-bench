# qvac-agent-bench

[![tests](https://github.com/latewatt/qvac-agent-bench/actions/workflows/ci.yml/badge.svg)](https://github.com/latewatt/qvac-agent-bench/actions/workflows/ci.yml)
[![sdk-smoke](https://github.com/latewatt/qvac-agent-bench/actions/workflows/sdk-smoke.yml/badge.svg)](https://github.com/latewatt/qvac-agent-bench/actions/workflows/sdk-smoke.yml)
![license](https://img.shields.io/badge/license-Apache--2.0-blue)

**Agent-readiness checks for [QVAC](https://qvac.tether.io), Tether's local AI stack.** Which local models can a coding agent actually rely on for tool calls, and does the SDK still install cleanly for a new user?

QVAC's own docs say reliable local tool use "generally needs >= 14B parameters", recommend `qwen3.5-9b` as the default agent model, and call `qwen3.5-0.8b` a connectivity check. There are no published per-model numbers behind that guidance, and the SDK ships every week or two with breaking changes. This repo measures both, reproducibly, against a real `qvac serve`.

## What it checks

| Check | What it does | Status |
|---|---|---|
| **SDK fresh-install smoke** | Installs `@qvac/sdk` from npm and `tetherto-qvac-sdk` from PyPI into empty environments, starts the real worker, and round-trips a heartbeat from both clients. No model needed. | Working, results below |
| **Tool-call conformance** | 22 cases across 8 categories sent to `qvac serve --openai`, scored against JSON Schema and expected calls, including calls the server silently drops. | Suite and scorer done; model runs in progress |
| **Coding tasks** | Runs the [small-model-harness](https://github.com/latewatt/small-model-harness) `mini-v1` suite (10 sandboxed tasks with hidden verifiers) through `qvac serve`. | Wired up via `make coding` |

## First finding: Python SDK fresh installs before 0.23.0 are broken

The 0.23.0 release notes say a fresh install of the 0.22.0 Python SDK fails because `bare-rpc` 0.1.0 (2026-10-28) removed an argument the client uses. The smoke test shows the same failure in **every earlier Python version tested**, not just 0.22.0: on a fresh install, pip resolves `bare-rpc` 0.2.0 for all of them.


| SDK version | JS client | Python client | bare-rpc resolved | Python error |
|---|---|---|---|---|
| 0.20.1 | PASS | FAIL | 0.2.0 | `TypeError: RPC.__init__() got an unexpected keyword argument 'send'` |
| 0.21.0 | PASS | FAIL | 0.2.0 | same |
| 0.21.1 | PASS | FAIL | 0.2.0 | same |
| 0.22.0 | PASS | FAIL | 0.2.0 | same |
| 0.23.0 | PASS | PASS | 0.0.1 | |

Linux x86_64, Node 22, Python 3.13, checked 2026-11-08. Raw output is in [`results/sdk-smoke/`](results/sdk-smoke/). Anyone pinned to a pre-0.23.0 Python SDK needs `pip install "bare-rpc<0.1"` until they upgrade. The weekly [`sdk-smoke`](.github/workflows/sdk-smoke.yml) workflow is meant to catch this kind of break the week it happens.

## Quickstart

Needs Python 3.11+ and Node 22+.

```sh
make setup          # Python venv with the bench installed
make test           # offline tests: scorer, suite, config, server lifecycle, report

make smoke          # SDK fresh-install checks for 0.20.1 … 0.23.0 (~3 GB of npm installs per version, cleaned up after)

make install-qvac   # pinned @qvac/cli 0.18.0 + @qvac/sdk 0.23.0 into qvac/node_modules
make toolcalls MODELS=qwen3.5-0.8b,qwen3.5-4b,qwen3.5-9b
make report         # regenerate RESULTS.md from results/
```

`make toolcalls` writes a `qvac.config.json` (tools on, greedy sampling, thinking off), starts `qvac serve --openai` on port 11460, runs the suite once per model, and stops the server. The first request to each model downloads and loads it. To test a server you started yourself, pass `--base-url`:

```sh
.venv/bin/python -m qvac_bench.cli toolcalls --base-url http://127.0.0.1:11434/v1 --models qwen3.5-9b
```

Model aliases map to QVAC catalog constants in [`models.json`](models.json). All six resolve in QVAC 0.23.0's catalog:

| Alias | Catalog constant | Download |
|---|---|---:|
| `qwen3.5-0.8b` | `QWEN3_5_0_8B_MULTIMODAL_Q4_K_M` | 0.53 GB |
| `qwen3.5-2b` | `QWEN3_5_2B_MULTIMODAL_Q4_K_M` | 1.28 GB |
| `qwen3.5-4b` | `QWEN3_5_4B_MULTIMODAL_Q4_K_M` | 2.74 GB |
| `qwen3.5-9b` | `QWEN3_5_9B_MULTIMODAL_Q4_K_M` | 5.68 GB |
| `qwen3-8b` | `QWEN3_8B_INST_Q4_K_M` | 5.03 GB |
| `gpt-oss-20b` | `GPT_OSS_20B_INST_Q4_K_M` | 11.62 GB |

## The tool-call suite

Tools look like a coding agent's (`read_file`, `edit_file`, `run_command`, `search_code`, `git_commit`, …) plus a few general ones. Each case is one request; [`build_cases.py`](suites/toolcalls-v1/build_cases.py) is the source of truth.

| Category | Cases | Tests |
|---|---:|---|
| `single` | 4 | One obvious tool, simple arguments |
| `selection` | 3 | Several plausible tools, one right one |
| `args` | 5 | Integers, enums, arrays and exact values the schema constrains |
| `no_tool` | 3 | Tools are offered but the right move is to answer |
| `parallel` | 2 | Two independent calls in one response |
| `forced` | 2 | `tool_choice: "required"` and a named tool |
| `multi_turn` | 2 | Answering, or chaining the next call, after a tool result |
| `deferred` | 1 | `defer_loading` tools reached through QVAC's built-in `tool_search` |

Every response gets exactly one outcome: `pass`, `invalid_args` (not JSON, or fails the schema), `wrong_tool`, `wrong_args`, `missing_calls`, `extra_calls`, `no_call`, `unexpected_call`, `wrong_answer`, `unknown_tool`, `error`, or **`dropped_call`**. That last one matters for QVAC specifically: when a model emits a tool call the server can't parse, `qvac serve` drops it and returns a plain `finish_reason: "stop"`. A client sees "the model chose not to call a tool". The bench reads the server log (`toolerrors=N`) for each request so those cases are counted as what they are.

Every case's own expectation is replayed through the scorer in the test suite, so no case is unpassable by construction.

## Caveats

- QVAC ignores request-level `seed`, so runs use greedy sampling but are not guaranteed bit-identical.
- Thinking is turned off with `reasoning_budget: 0` to compare models on equal terms. Agents that allow thinking may score differently.
- One attempt per case. With 22 cases, a difference of one or two passes between models is noise.
- `dropped_call` detection needs the bench to own the server log; with `--base-url` it can't distinguish a dropped call from a plain answer.

## Roadmap

See [docs/roadmap.md](docs/roadmap.md): 50+ tool-call cases, 40 coding tasks through `qvac serve` and the OpenCode plugin, Apple Silicon and Linux results for 6+ models, ablations (context size, `tool_search`, speculative decoding), a release-regression workflow, and a "choosing a local model for agents" docs page.

## License

Apache-2.0, matching QVAC.
