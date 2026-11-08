"""Fresh-install smoke tests for the QVAC JS and Python SDKs.

For each version: install `@qvac/sdk@<v>` from npm and `tetherto-qvac-sdk==<v>`
from PyPI into empty environments (so dependency ranges resolve the way a new
user's would), start the real worker, and round-trip a heartbeat from both
clients. Nothing is loaded or downloaded beyond the packages themselves.

This is the check that would have caught 0.22.0: its Python package allowed
`bare-rpc>=0.0.1`, and bare-rpc 0.1.0 (2026-10-28) removed the `send=` argument
the client passes, so every fresh install failed on connect.
"""
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import ROOT

SMOKE = ROOT / "smoke"


def _run(cmd, cwd=None, env=None, timeout=900):
    started = time.monotonic()
    proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    return proc, round(time.monotonic() - started, 1)


def _last_json(text: str) -> dict:
    for line in reversed(text.strip().splitlines()):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    return {"ok": False, "error": text.strip()[-500:] or "no output"}


def find_bare(node_modules: Path) -> Path | None:
    for candidate in sorted(node_modules.glob("**/bare-runtime-*/bin/bare")):
        if candidate.is_file():
            return candidate
    return None


def install_js(version: str, workdir: Path) -> dict:
    js = workdir / "js"
    js.mkdir(parents=True)
    (js / "package.json").write_text(json.dumps({"name": "qvac-smoke", "private": True, "type": "module"}))
    proc, secs = _run(["npm", "install", "--ignore-scripts", "--no-audit", "--no-fund", f"@qvac/sdk@{version}"], cwd=js)
    if proc.returncode:
        return {"ok": False, "error": proc.stderr.strip()[-500:], "install_s": secs}
    bare = find_bare(js / "node_modules")
    worker = js / "node_modules/@qvac/sdk/dist/src/worker/index.js"
    if not bare or not worker.exists():
        return {"ok": False, "error": "worker or bare runtime missing after install", "install_s": secs}
    # --ignore-scripts skips the step that marks the runtime executable.
    bare.chmod(bare.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return {"ok": True, "dir": js, "bare": bare, "worker": worker, "install_s": secs}


def check_js(js: dict) -> dict:
    shutil.copy(SMOKE / "js_heartbeat.mjs", js["dir"] / "heartbeat.mjs")
    proc, secs = _run(["node", "heartbeat.mjs"], cwd=js["dir"], timeout=120)
    return {**_last_json(proc.stdout or proc.stderr), "run_s": secs}


def check_python(version: str, js: dict, workdir: Path) -> dict:
    venv = workdir / "venv"
    proc, _ = _run([sys.executable, "-m", "venv", str(venv)])
    if proc.returncode:
        return {"ok": False, "error": proc.stderr.strip()[-500:]}
    python = venv / "bin" / "python"
    proc, secs = _run([str(python), "-m", "pip", "install", "-q", "--disable-pip-version-check",
                       f"tetherto-qvac-sdk=={version}"])
    if proc.returncode:
        return {"ok": False, "error": proc.stderr.strip()[-500:], "install_s": secs}
    freeze, _ = _run([str(python), "-m", "pip", "freeze"])
    resolved = {line.split("==")[0]: line.split("==")[1] for line in freeze.stdout.splitlines() if "==" in line}
    env = {**os.environ, "QVAC_WORKER_PATH": str(js["worker"]), "QVAC_BARE_PATH": str(js["bare"])}
    proc, run_s = _run([str(python), str(SMOKE / "py_heartbeat.py")], env=env, timeout=120)
    return {**_last_json(proc.stdout or proc.stderr), "install_s": secs, "run_s": run_s,
            "bare_rpc": resolved.get("bare-rpc", "?")}


def smoke_version(version: str, scratch: Path, keep: bool = False) -> dict:
    workdir = scratch / version
    shutil.rmtree(workdir, ignore_errors=True)
    workdir.mkdir(parents=True)
    try:
        js = install_js(version, workdir)
        if not js["ok"]:
            return {"version": version, "js": js, "python": {"ok": False, "error": "skipped: JS worker install failed"}}
        result = {"version": version, "js": check_js(js), "python": check_python(version, js, workdir)}
        result["js"]["install_s"] = js["install_s"]
        return result
    finally:
        if not keep:
            shutil.rmtree(workdir, ignore_errors=True)


def run(versions: list[str], out_dir: Path, scratch: Path, keep: bool = False) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
    host = f"{platform.system().lower()}-{platform.machine()}"
    results = []
    for version in versions:
        print(f"[smoke] @qvac/sdk + tetherto-qvac-sdk {version} ...", flush=True)
        results.append(smoke_version(version, scratch, keep))
        r = results[-1]
        print(f"        js={'PASS' if r['js'].get('ok') else 'FAIL'} "
              f"python={'PASS' if r['python'].get('ok') else 'FAIL'}", flush=True)
    node, _ = _run(["node", "--version"])
    report = {"checked_at": stamp, "host": host, "python": platform.python_version(),
              "node": node.stdout.strip(), "results": results}
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{stamp[:10]}-{host}.json"
    path.write_text(json.dumps(report, indent=2, default=str) + "\n")
    return path
