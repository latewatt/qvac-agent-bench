# Roadmap

The goal is a public, reproducible answer to "which QVAC models can a local agent rely on, and did this release break anything?", kept current as QVAC ships.

## Now (prototype)

- [x] SDK fresh-install smoke test for the JS and Python clients, with a weekly CI run
- [x] `qvac serve` lifecycle, config generation and catalog checks
- [x] Tool-call conformance suite v1 (22 cases, 8 categories) and scorer, including dropped-call detection
- [ ] First model matrix: `qwen3.5` 0.8B / 2B / 4B / 9B on a 16 GB Apple Silicon laptop
- [ ] `mini-v1` coding tasks through `qvac serve` for the same models

## Milestone 1: install and tool-call baseline

- Smoke tests across the last three SDK releases on macOS and Linux, in CI
- Tool-call suite grown to 50+ cases, including `tool_search` and parallel calls (on by default since 0.23.0)
- Results for at least 4 models on Apple Silicon

## Milestone 2: coding agents

- 40+ sandboxed coding tasks run through `qvac serve` and through the OpenCode plugin
- Results for 6+ models on Apple Silicon and Linux, with time-to-first-token, tokens/s and memory

## Milestone 3: what moves the numbers

- Ablations: context size, `tool_search` on/off, speculative decoding (new in 0.23.0), thinking on/off
- A failure taxonomy per model, with an upstream issue or PR for each bug found

## Milestone 4: agents with wallets

- A local QVAC agent driving the WDK CLI MCP server on testnet only
- Scenarios for spending limits, confirmation bypass, prompt injection and seed exfiltration, scored per model

## Milestone 5: upstream

- A "choosing a local model for agents" docs page with the measured matrix
- A release-regression workflow the QVAC team can run on each release
