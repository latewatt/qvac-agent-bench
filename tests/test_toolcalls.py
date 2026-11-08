import json

import pytest

from qvac_bench import toolcalls
from qvac_bench.client import ChatClient, ChatResult

TOOLS, CASES = toolcalls.load_suite()
BY_ID = {c["id"]: c for c in CASES}


def result_with(*calls, content=None, ok=True):
    tool_calls = [{"id": "c", "type": "function",
                   "function": {"name": n, "arguments": a if isinstance(a, str) else json.dumps(a)}} for n, a in calls]
    body = {"choices": [{"message": {"content": content, "tool_calls": tool_calls}, "finish_reason": "stop"}]}
    return ChatResult(ok, 200 if ok else 503, 0.1, body if ok else {}, "" if ok else "model_load_timeout")


def outcome(case_id, result, dropped=0):
    return toolcalls.score(BY_ID[case_id], result, TOOLS, dropped)[0]


def test_suite_is_well_formed():
    assert len(CASES) >= 20
    for case in CASES:
        assert case["expect"]["type"] in {"call", "no_call"}
        for want in case["expect"].get("calls", []):
            assert want["name"] in case["tools"], case["id"]
            # every exact expectation must itself satisfy the tool's schema types
            for key in want.get("args", {}):
                assert key in TOOLS[want["name"]]["parameters"]["properties"], (case["id"], key)


def test_pass_and_value_normalisation():
    assert outcome("single-weather", result_with(("get_weather", {"city": "  lisbon "}))) == "pass"
    assert outcome("single-currency", result_with(("convert_currency", {"amount": 250.0, "from_currency": "usd", "to_currency": "EUR"}))) == "pass"
    # list order does not matter
    args = {"title": "Design review", "date": "2026-12-03", "start_time": "14:30", "duration_minutes": 45,
            "attendees": ["raj@example.com", "ana@example.com"]}
    assert outcome("args-meeting", result_with(("schedule_meeting", args))) == "pass"


def test_schema_violations_are_invalid_args():
    assert outcome("args-line-range", result_with(("read_file", {"path": "lib/db.py", "start_line": "40"}))) == "invalid_args"
    assert outcome("single-read-file", result_with(("read_file", "{path: src/app.py}"))) == "invalid_args"
    assert outcome("args-issue-enums", result_with(("create_issue", {"title": "x", "labels": ["urgent"], "priority": "high"}))) == "invalid_args"


def test_wrong_tool_wrong_args_and_unknown_tool():
    assert outcome("select-search-not-read", result_with(("read_file", {"path": "src/config.py"}))) == "wrong_tool"
    assert outcome("single-weather", result_with(("get_weather", {"city": "Porto"}))) == "wrong_args"
    assert outcome("single-weather", result_with(("get_forecast", {"city": "Lisbon"}))) == "unknown_tool"


def test_missing_and_extra_calls():
    one = result_with(("get_weather", {"city": "Oslo"}))
    assert outcome("parallel-weather", one) == "missing_calls"
    both = result_with(("get_weather", {"city": "Oslo"}), ("get_weather", {"city": "Nairobi"}))
    assert outcome("parallel-weather", both) == "pass"
    extra = result_with(("list_dir", {"path": "."}), ("read_file", {"path": "README.md"}))
    assert outcome("forced-named", extra) == "extra_calls"


def test_no_call_cases():
    assert outcome("none-capital", result_with(content="Tokyo.")) == "pass"
    assert outcome("none-capital", result_with(("get_weather", {"city": "Tokyo"}))) == "unexpected_call"
    assert outcome("multi-answer-after-result", result_with(content="It's sunny and 19°C in Rome.")) == "pass"
    assert outcome("multi-answer-after-result", result_with(content="It's sunny in Rome.")) == "wrong_answer"


def test_dropped_calls_are_distinguished_from_plain_answers():
    answer = result_with(content="Sure, reading it now.")
    assert outcome("single-read-file", answer) == "no_call"
    assert outcome("single-read-file", answer, dropped=1) == "dropped_call"


def test_transport_errors():
    assert outcome("single-weather", result_with(ok=False)) == "error"


def test_deferred_tools_are_marked():
    tools = toolcalls.request_tools(BY_ID["deferred-email"], TOOLS)
    deferred = {t["function"]["name"] for t in tools if t.get("defer_loading")}
    assert deferred == {"get_weather", "convert_currency", "schedule_meeting", "send_email", "send_sms"}
    assert not any(t.get("defer_loading") for t in tools if t["function"]["name"] == "read_file")


def test_run_suite_end_to_end(fake, tmp_path):
    fake.reply_calls(("read_file", {"path": "src/app.py"}))
    fake.reply_text("I would rather not.")
    rows = toolcalls.run_suite(ChatClient(fake.base_url), "fake", out_path=tmp_path / "out.jsonl",
                               only={"single-read-file", "single-run-tests"})
    assert [r["outcome"] for r in rows] == ["pass", "no_call"]
    sent = fake.requests[0]
    assert sent["model"] == "fake" and sent["temperature"] == 0.0
    assert {t["function"]["name"] for t in sent["tools"]} >= {"read_file", "run_command"}
    assert len((tmp_path / "out.jsonl").read_text().splitlines()) == 2
    summary = toolcalls.summarize(rows)
    assert summary["passed"] == 1 and summary["by_category"]["single"] == {"pass": 1, "total": 2}


def test_forced_choice_and_parallel_flags_are_sent(fake):
    # Cases run in file order: parallel-weather comes before forced-named.
    fake.reply_calls(("get_weather", {"city": "Oslo"}), ("get_weather", {"city": "Nairobi"}))
    fake.reply_calls(("list_dir", {"path": "."}))
    rows = toolcalls.run_suite(ChatClient(fake.base_url), "fake", only={"forced-named", "parallel-weather"})
    assert [r["outcome"] for r in rows] == ["pass", "pass"]
    parallel, forced = fake.requests
    assert forced["tool_choice"] == {"type": "function", "function": {"name": "list_dir"}}
    assert parallel["parallel_tool_calls"] is True


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_reference_answer_passes(case):
    """Each case is satisfiable: its own expectation, replayed as a response, scores pass."""
    if case["expect"]["type"] == "no_call":
        text = " ".join(case["expect"].get("answer_contains", [])) or "Answer."
        assert toolcalls.score(case, result_with(content=text), TOOLS)[0] == "pass"
        return
    calls = []
    for want in case["expect"]["calls"]:
        params = TOOLS[want["name"]]["parameters"]
        args = dict(want.get("args", {}))
        for key, fragment in want.get("args_contains", {}).items():
            args[key] = fragment
        for key in params.get("required", []):
            if key not in args:
                kind = params["properties"][key].get("type")
                args[key] = {"integer": 5, "number": 1.0, "array": ["x"], "boolean": True}.get(kind, "x")
                if "enum" in params["properties"][key]:
                    args[key] = params["properties"][key]["enum"][0]
        calls.append((want["name"], args))
    assert toolcalls.score(case, result_with(*calls), TOOLS)[0] == "pass", case["id"]
