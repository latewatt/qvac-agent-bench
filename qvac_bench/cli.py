"""qvac-bench: run the tool-call suite and SDK smoke tests, then render results."""
import argparse
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import ROOT, report, smoke, toolcalls
from .client import ChatClient
from .server import QvacServer, build_config, qvac_command


def load_models(names: str) -> dict:
    catalog = json.loads((ROOT / "models.json").read_text())
    chosen = [n.strip() for n in names.split(",") if n.strip()]
    unknown = [n for n in chosen if n not in catalog]
    if unknown:
        sys.exit(f"unknown model alias {unknown}; edit models.json (known: {', '.join(catalog)})")
    return {n: catalog[n] for n in chosen}


def cli_version() -> str:
    try:
        out = subprocess.run(qvac_command() + ["--version"], capture_output=True, text=True, timeout=60)
        return out.stdout.strip() or "?"
    except (OSError, subprocess.TimeoutExpired):
        return "?"


def cmd_toolcalls(args):
    models = load_models(args.models)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
    host = f"{platform.system().lower()}-{platform.machine()}"
    out = ROOT / "results" / "toolcalls" / f"{stamp}-{host}"
    out.mkdir(parents=True, exist_ok=True)
    only = set(args.only.split(",")) if args.only else None
    _, cases = toolcalls.load_suite()
    summary = {"meta": {"host": host, "suite": "toolcalls-v1", "cases": len(cases), "started": stamp,
                        "max_tokens": args.max_tokens, "base_url": args.base_url or "managed",
                        "qvac_cli": "external" if args.base_url else cli_version(),
                        "models": models}, "models": {}}
    server = None
    if args.base_url:
        client = ChatClient(args.base_url)
    else:
        server = QvacServer(out, models, port=args.port, ctx_size=args.ctx_size).start()
        client = ChatClient(server.base_url)
    try:
        for alias in models:
            print(f"[toolcalls] {alias}: first request loads the model (and downloads it if needed) ...", flush=True)
            rows = toolcalls.run_suite(client, alias, server=server, out_path=out / f"{alias}.jsonl",
                                       max_tokens=args.max_tokens, only=only)
            summary["models"][alias] = toolcalls.summarize(rows)
            s = summary["models"][alias]
            print(f"[toolcalls] {alias}: {s['passed']}/{s['cases']} passed, outcomes {s['outcomes']}", flush=True)
            (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    finally:
        if server:
            server.stop()
    print(f"[toolcalls] wrote {out.relative_to(ROOT)}")


def cmd_serve(args):
    models = load_models(args.models)
    server = QvacServer(ROOT / ".cache" / "serve", models, port=args.port, ctx_size=args.ctx_size).start()
    print(f"[serve] {server.base_url} serving {', '.join(models)}; log at {server.log_path}. Ctrl-C to stop.", flush=True)
    try:
        server.process.wait()
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()


def cmd_catalog(args):
    client = ChatClient(args.base_url)
    query = f"?search={args.search}&role=chat" if args.search else "?role=chat"
    _, body = client._request("GET", "/models/catalog" + query)
    for row in body.get("data", []):
        print(f"{row['id']:<45} {row.get('params', ''):>6}  {row.get('quantization', ''):<8} "
              f"{'configured' if row.get('configured') else ''}")


def cmd_config(args):
    print(json.dumps(build_config(load_models(args.models), cache_dir=ROOT / ".cache" / "models"), indent=2))


def cmd_smoke(args):
    versions = [v.strip() for v in args.versions.split(",") if v.strip()]
    if "latest" in versions:
        latest = subprocess.run(["npm", "view", "@qvac/sdk", "version"], capture_output=True, text=True,
                                timeout=120).stdout.strip()
        versions = [latest if v == "latest" else v for v in versions]
    path = smoke.run(versions, ROOT / "results" / "sdk-smoke", ROOT / ".cache" / "smoke", keep=args.keep)
    print(f"[smoke] wrote {path.relative_to(ROOT)}")
    data = json.loads(path.read_text())
    if args.fail_on_regression and not all(r["js"].get("ok") and r["python"].get("ok") for r in data["results"]):
        sys.exit(1)


def cmd_report(args):
    print(f"wrote {report.write().relative_to(ROOT)}")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="qvac-bench", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("toolcalls", help="run the tool-call conformance suite")
    p.add_argument("--models", default="qwen3.5-0.8b,qwen3.5-2b,qwen3.5-4b,qwen3.5-9b")
    p.add_argument("--base-url", help="use an already running server instead of starting one")
    p.add_argument("--port", type=int, default=11460)
    p.add_argument("--ctx-size", type=int, default=8192)
    p.add_argument("--max-tokens", type=int, default=512)
    p.add_argument("--only", help="comma-separated case ids or categories")
    p.set_defaults(func=cmd_toolcalls)

    p = sub.add_parser("serve", help="start qvac serve with the given models and keep it running")
    p.add_argument("--models", default="qwen3.5-4b")
    p.add_argument("--port", type=int, default=11460)
    p.add_argument("--ctx-size", type=int, default=8192)
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("catalog", help="list chat models a running server knows about")
    p.add_argument("--base-url", default="http://127.0.0.1:11460/v1")
    p.add_argument("--search", default="")
    p.set_defaults(func=cmd_catalog)

    p = sub.add_parser("config", help="print the qvac.config.json the bench would use")
    p.add_argument("--models", default="qwen3.5-0.8b,qwen3.5-2b,qwen3.5-4b,qwen3.5-9b")
    p.set_defaults(func=cmd_config)

    p = sub.add_parser("smoke", help="fresh-install the JS and Python SDKs and round-trip a heartbeat")
    p.add_argument("--versions", default="0.20.1,0.21.0,0.21.1,0.22.0,0.23.0")
    p.add_argument("--keep", action="store_true", help="keep the scratch installs")
    p.add_argument("--fail-on-regression", action="store_true")
    p.set_defaults(func=cmd_smoke)

    p = sub.add_parser("report", help="regenerate RESULTS.md")
    p.set_defaults(func=cmd_report)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
