import json

from qvac_bench import report


def test_report_renders_saved_results(tmp_path):
    run = tmp_path / "toolcalls" / "2026-11-09T0000Z-darwin-arm64"
    run.mkdir(parents=True)
    summary = {"meta": {"host": "darwin-arm64", "suite": "toolcalls-v1", "cases": 2, "qvac_cli": "0.18.0"},
               "models": {"qwen3.5-4b": {"cases": 2, "passed": 1, "by_category": {"single": {"pass": 1, "total": 2}},
                                         "outcomes": {"pass": 1, "no_call": 1}, "median_latency_s": 1.2,
                                         "completion_tokens": 40, "dropped_tool_calls": 0}}}
    (run / "summary.json").write_text(json.dumps(summary))
    smoke = tmp_path / "sdk-smoke"
    smoke.mkdir()
    (smoke / "2026-11-09-linux-x86_64.json").write_text(json.dumps({
        "node": "v22", "python": "3.12", "results": [
            {"version": "0.22.0", "js": {"ok": True}, "python": {"ok": False, "bare_rpc": "0.2.0",
                                                                "error": "TypeError: RPC.__init__() got an unexpected keyword argument 'send'"}}]}))
    text = report.render(tmp_path)
    assert "| `qwen3.5-4b` | **1/2** | 1/2 |" in text
    assert "no_call ×1" in text
    assert "| 0.22.0 | PASS | FAIL | 0.2.0 |" in text
