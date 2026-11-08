"""Writes cases.jsonl. Edit cases here, then run: python suites/toolcalls-v1/build_cases.py"""
import json
from pathlib import Path

CODING = ["read_file", "write_file", "edit_file", "run_command", "search_code", "list_dir", "git_commit", "create_issue"]
GENERAL = ["get_weather", "convert_currency", "schedule_meeting", "send_email", "send_sms"]


def user(text):
    return [{"role": "user", "content": text}]


def call(name, args=None, contains=None):
    spec = {"name": name}
    if args:
        spec["args"] = args
    if contains:
        spec["args_contains"] = contains
    return spec


CASES = [
    # single: one obvious tool, simple arguments
    dict(id="single-read-file", category="single", tools=CODING,
         messages=user("Show me the contents of src/app.py."),
         expect={"type": "call", "calls": [call("read_file", {"path": "src/app.py"})]}),
    dict(id="single-run-tests", category="single", tools=CODING,
         messages=user("Run the test suite with `pytest -q`."),
         expect={"type": "call", "calls": [call("run_command", {"command": "pytest -q"})]}),
    dict(id="single-weather", category="single", tools=GENERAL,
         messages=user("What's the weather like in Lisbon right now?"),
         expect={"type": "call", "calls": [call("get_weather", {"city": "Lisbon"})]}),
    dict(id="single-currency", category="single", tools=GENERAL,
         messages=user("How much is 250 US dollars in euros today?"),
         expect={"type": "call", "calls": [call("convert_currency", {"amount": 250, "from_currency": "USD", "to_currency": "EUR"})]}),

    # selection: several plausible tools, one right answer
    dict(id="select-search-not-read", category="selection", tools=CODING,
         messages=user("Find every place in the codebase that calls `parse_config`. I don't know which files."),
         expect={"type": "call", "calls": [call("search_code", contains={"query": "parse_config"})]}),
    dict(id="select-list-not-read", category="selection", tools=CODING,
         messages=user("What files are in the tests directory?"),
         expect={"type": "call", "calls": [call("list_dir", contains={"path": "tests"})]}),
    dict(id="select-sms-not-email", category="selection", tools=GENERAL,
         messages=user("Text +1 555 0100 and tell them I'm running ten minutes late."),
         expect={"type": "call", "calls": [call("send_sms", contains={"text": "late"})]}),

    # args: types the schema constrains (integers, enums, arrays, nested values)
    dict(id="args-line-range", category="args", tools=CODING,
         messages=user("Read lines 40 to 60 of lib/db.py."),
         expect={"type": "call", "calls": [call("read_file", {"path": "lib/db.py", "start_line": 40, "end_line": 60})]}),
    dict(id="args-enum-unit", category="args", tools=GENERAL,
         messages=user("What's the temperature in Chicago in Fahrenheit?"),
         expect={"type": "call", "calls": [call("get_weather", {"city": "Chicago", "unit": "fahrenheit"})]}),
    dict(id="args-issue-enums", category="args", tools=CODING,
         messages=user("Open a high-priority bug titled 'Login fails on Safari'. Body: users on Safari 18 get a blank page after submitting the form."),
         expect={"type": "call", "calls": [call("create_issue", {"labels": ["bug"], "priority": "high"}, contains={"title": "safari"})]}),
    dict(id="args-meeting", category="args", tools=GENERAL,
         messages=user("Schedule a 45 minute 'Design review' on 2026-12-03 at 14:30 with ana@example.com and raj@example.com."),
         expect={"type": "call", "calls": [call("schedule_meeting", {"date": "2026-12-03", "start_time": "14:30", "duration_minutes": 45,
                                                                       "attendees": ["ana@example.com", "raj@example.com"]})]}),
    dict(id="args-commit-files", category="args", tools=CODING,
         messages=user("Commit src/auth.py and tests/test_auth.py with the message 'Fix token expiry check'."),
         expect={"type": "call", "calls": [call("git_commit", {"files": ["src/auth.py", "tests/test_auth.py"]}, contains={"message": "token expiry"})]}),

    # no_tool: tools are available but the right move is to answer directly
    dict(id="none-arithmetic", category="no_tool", tools=CODING,
         messages=user("What is 17 times 3? Just tell me."),
         expect={"type": "no_call"}),
    dict(id="none-concept", category="no_tool", tools=CODING,
         messages=user("In one sentence, what does a Python list comprehension do?"),
         expect={"type": "no_call"}),
    dict(id="none-capital", category="no_tool", tools=GENERAL,
         messages=user("What's the capital of Japan?"),
         expect={"type": "no_call"}),

    # parallel: two independent calls in one response
    dict(id="parallel-weather", category="parallel", tools=GENERAL, parallel_tool_calls=True,
         messages=user("Get the current weather in both Oslo and Nairobi."),
         expect={"type": "call", "calls": [call("get_weather", {"city": "Oslo"}), call("get_weather", {"city": "Nairobi"})]}),
    dict(id="parallel-read-two", category="parallel", tools=CODING, parallel_tool_calls=True,
         messages=user("Open both README.md and setup.cfg so I can compare them."),
         expect={"type": "call", "calls": [call("read_file", {"path": "README.md"}), call("read_file", {"path": "setup.cfg"})]}),

    # forced: tool_choice constrains generation with the template grammar
    dict(id="forced-named", category="forced", tools=CODING,
         tool_choice={"type": "function", "function": {"name": "list_dir"}},
         messages=user("Let's look at the project root."),
         expect={"type": "call", "calls": [call("list_dir")]}),
    dict(id="forced-required", category="forced", tools=CODING, tool_choice="required",
         messages=user("Check whether the build passes: the command is `make build`."),
         expect={"type": "call", "calls": [call("run_command", {"command": "make build"})]}),

    # multi_turn: continue correctly after a tool result
    dict(id="multi-answer-after-result", category="multi_turn", tools=GENERAL,
         messages=[
             {"role": "user", "content": "What's the weather in Rome?"},
             {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1", "type": "function",
                 "function": {"name": "get_weather", "arguments": json.dumps({"city": "Rome"})}}]},
             {"role": "tool", "tool_call_id": "call_1", "content": json.dumps({"city": "Rome", "temp_c": 19, "conditions": "sunny"})},
         ],
         expect={"type": "no_call", "answer_contains": ["19"]}),
    dict(id="multi-chain-search-then-read", category="multi_turn", tools=CODING,
         messages=[
             {"role": "user", "content": "Find where `retry_backoff` is defined and show me that file."},
             {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1", "type": "function",
                 "function": {"name": "search_code", "arguments": json.dumps({"query": "def retry_backoff"})}}]},
             {"role": "tool", "tool_call_id": "call_1", "content": "net/retry.py:12: def retry_backoff(attempt, base=0.5):"},
         ],
         expect={"type": "call", "calls": [call("read_file", {"path": "net/retry.py"})]}),

    # deferred: schemas stay out of the prompt until the model asks via tool_search
    dict(id="deferred-email", category="deferred", tools=CODING + GENERAL, deferred=GENERAL,
         messages=user("Email sam@example.com with the subject 'Release notes' and say the release is ready."),
         expect={"type": "call", "calls": [call("send_email", {"to": "sam@example.com"}, contains={"subject": "release notes"})]}),
]

if __name__ == "__main__":
    out = Path(__file__).with_name("cases.jsonl")
    ids = [c["id"] for c in CASES]
    assert len(ids) == len(set(ids)), "duplicate case ids"
    out.write_text("".join(json.dumps(c, sort_keys=True) + "\n" for c in CASES))
    print(f"wrote {len(CASES)} cases to {out}")
