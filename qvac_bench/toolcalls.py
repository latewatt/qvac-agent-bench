"""Tool-call conformance: does the model call the right tool, with valid arguments, only when it should?

Each case sends one chat request and scores the response. Outcomes, in the
order they are checked:

    error            HTTP or transport failure
    unknown_tool     called a tool that was not offered
    invalid_args     arguments are not JSON or do not match the tool's schema
    dropped_call     no tool call returned, but the server log shows it parsed
                     and dropped one (QVAC drops unparseable calls silently)
    no_call          a call was expected and none was made
    unexpected_call  the right move was to answer, but the model called a tool
    wrong_tool       none of the calls used the expected tool
    wrong_args       the expected tool was called with the wrong values
    missing_calls    fewer of the expected calls than required (e.g. parallel)
    extra_calls      every expected call was made, plus others
    wrong_answer     answered without a tool but missed required content
    pass
"""
import json
import statistics
from collections import Counter
from pathlib import Path

from jsonschema import Draft202012Validator

from .server import count_tool_errors

SUITE = Path(__file__).resolve().parents[1] / "suites" / "toolcalls-v1"


def load_suite(suite_dir: Path = SUITE):
    tools = json.loads((suite_dir / "tools.json").read_text())
    cases = [json.loads(line) for line in (suite_dir / "cases.jsonl").read_text().splitlines() if line.strip()]
    for case in cases:
        unknown = set(case["tools"]) - set(tools)
        if unknown:
            raise ValueError(f"{case['id']}: unknown tools {sorted(unknown)}")
    return tools, cases


def request_tools(case: dict, tools: dict) -> list[dict]:
    deferred = set(case.get("deferred", []))
    out = []
    for name in case["tools"]:
        entry = {"type": "function", "function": {"name": name, **tools[name]}}
        if name in deferred:
            entry["defer_loading"] = True
        out.append(entry)
    return out


def _norm(value):
    if isinstance(value, str):
        return " ".join(value.split()).casefold()
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, list):
        return sorted((_norm(v) for v in value), key=repr)
    return value


def args_match(expected: dict, actual: dict) -> bool:
    for key, want in expected.get("args", {}).items():
        if key not in actual or _norm(actual[key]) != _norm(want):
            return False
    for key, fragment in expected.get("args_contains", {}).items():
        value = actual.get(key)
        if not isinstance(value, str) or fragment.casefold() not in value.casefold():
            return False
    return True


def parse_calls(tool_calls: list, tools: dict, offered: set):
    """Return (parsed calls, first problem) where a problem is (outcome, detail)."""
    parsed = []
    for raw in tool_calls:
        function = raw.get("function") or {}
        name = function.get("name", "")
        if name not in offered:
            return parsed, ("unknown_tool", f"called {name!r}")
        try:
            args = json.loads(function.get("arguments") or "{}")
        except json.JSONDecodeError as exc:
            return parsed, ("invalid_args", f"{name}: arguments are not JSON ({exc.msg})")
        if not isinstance(args, dict):
            return parsed, ("invalid_args", f"{name}: arguments are not an object")
        errors = sorted(Draft202012Validator(tools[name]["parameters"]).iter_errors(args), key=str)
        if errors:
            return parsed, ("invalid_args", f"{name}: {errors[0].message}")
        parsed.append({"name": name, "args": args})
    return parsed, None


def score(case: dict, result, tools: dict, tool_errors: int = 0) -> tuple[str, str]:
    if not result.ok:
        return "error", f"HTTP {result.status}: {result.error[:300]}"
    expect = case["expect"]
    parsed, problem = parse_calls(result.tool_calls, tools, set(case["tools"]))
    if problem:
        return problem
    content = result.message.get("content") or ""
    if expect["type"] == "no_call":
        if parsed:
            return "unexpected_call", f"called {[c['name'] for c in parsed]}"
        missing = [s for s in expect.get("answer_contains", []) if s.casefold() not in content.casefold()]
        if missing:
            return "wrong_answer", f"answer lacks {missing}"
        return "pass", ""
    if not parsed:
        if tool_errors:
            return "dropped_call", f"server dropped {tool_errors} unparseable tool call(s)"
        return "no_call", f"answered instead: {content[:120]!r}"
    wanted = expect["calls"]
    if not any(c["name"] == w["name"] for c in parsed for w in wanted):
        return "wrong_tool", f"called {[c['name'] for c in parsed]}, expected {[w['name'] for w in wanted]}"
    remaining = list(parsed)
    matched = 0
    for want in wanted:
        hit = next((c for c in remaining if c["name"] == want["name"] and args_match(want, c["args"])), None)
        if hit:
            remaining.remove(hit)
            matched += 1
    if matched == 0:
        return "wrong_args", f"got {json.dumps([c['args'] for c in parsed])[:200]}"
    if matched < len(wanted):
        return "missing_calls", f"{matched}/{len(wanted)} expected calls"
    if remaining:
        return "extra_calls", f"extra {[c['name'] for c in remaining]}"
    return "pass", ""


def run_suite(client, model: str, *, server=None, suite_dir: Path = SUITE, out_path: Path | None = None,
              max_tokens: int = 512, only: set | None = None):
    tools, cases = load_suite(suite_dir)
    rows = []
    for case in cases:
        if only and case["id"] not in only and case["category"] not in only:
            continue
        offset = server.log_size() if server else 0
        result = client.chat(model, case["messages"], tools=request_tools(case, tools),
                             tool_choice=case.get("tool_choice"),
                             parallel_tool_calls=case.get("parallel_tool_calls"),
                             max_tokens=max_tokens)
        dropped = count_tool_errors(server.log_since(offset)) if server else 0
        outcome, detail = score(case, result, tools, dropped)
        row = {"model": model, "case": case["id"], "category": case["category"], "outcome": outcome,
               "detail": detail, "latency_s": round(result.latency_s, 3), "finish_reason": result.finish_reason,
               "usage": result.usage, "tool_calls": result.tool_calls,
               "content": (result.message.get("content") or "")[:500], "dropped_tool_calls": dropped}
        rows.append(row)
        if out_path:
            with open(out_path, "a") as f:
                f.write(json.dumps(row) + "\n")
    return rows


def summarize(rows: list[dict]) -> dict:
    by_category = {}
    for row in rows:
        stats = by_category.setdefault(row["category"], {"pass": 0, "total": 0})
        stats["total"] += 1
        stats["pass"] += row["outcome"] == "pass"
    latencies = [r["latency_s"] for r in rows if r["outcome"] != "error"]
    return {
        "cases": len(rows),
        "passed": sum(r["outcome"] == "pass" for r in rows),
        "by_category": by_category,
        "outcomes": dict(Counter(r["outcome"] for r in rows)),
        "median_latency_s": round(statistics.median(latencies), 3) if latencies else None,
        "completion_tokens": sum((r.get("usage") or {}).get("completion_tokens", 0) for r in rows),
        "dropped_tool_calls": sum(r.get("dropped_tool_calls", 0) for r in rows),
    }
