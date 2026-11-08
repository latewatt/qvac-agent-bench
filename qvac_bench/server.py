"""Write a qvac.config.json and own one `qvac serve --openai` process."""
import json
import os
import re
import shlex
import signal
import subprocess
import time
import urllib.request
from pathlib import Path

from . import ROOT

DEFAULT_CLI = ROOT / "qvac" / "node_modules" / ".bin" / "qvac"
TOOL_ERRORS = re.compile(r"toolerrors=(\d+)")


def qvac_command() -> list[str]:
    """`QVAC_CMD` overrides the pinned CLI installed by `make install-qvac`."""
    if os.environ.get("QVAC_CMD"):
        return shlex.split(os.environ["QVAC_CMD"])
    return [str(DEFAULT_CLI)]


def build_config(models: dict, *, cache_dir: Path, ctx_size: int = 8192, predict: int = 1024) -> dict:
    """One serve.models alias per catalog constant, all with tool calling on.

    Sampling is greedy and thinking is off so runs are comparable across models.
    QVAC ignores request-level `seed`, so repeat runs are not guaranteed identical.
    """
    entries = {}
    for i, (alias, spec) in enumerate(models.items()):
        entries[alias] = {
            "model": spec["model"],
            "default": i == 0,
            "preload": False,
            "config": {"ctx_size": spec.get("ctx_size", ctx_size), "tools": True, "temp": 0,
                       "predict": predict, "reasoning_budget": 0},
        }
    return {
        "cacheDirectory": str(cache_dir),
        "loggerConsoleOutput": True,
        "loggerLevel": "info",
        "serve": {"models": entries, "load": {"concurrency": 1}},
    }


def count_tool_errors(log_text: str) -> int:
    """Tool calls the server parsed and dropped (`toolerrors=N` in its log)."""
    return sum(int(n) for n in TOOL_ERRORS.findall(log_text))


class QvacServer:
    def __init__(self, workdir: Path, models: dict, *, port: int = 11460, ctx_size: int = 8192,
                 load_timeout_s: int = 1800):
        self.workdir = Path(workdir).resolve()
        self.models = models
        self.port = port
        self.ctx_size = ctx_size
        self.load_timeout_s = load_timeout_s
        self.config_path = self.workdir / "qvac.config.json"
        self.log_path = self.workdir / "qvac-server.log"
        self.process = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def write_config(self) -> Path:
        self.workdir.mkdir(parents=True, exist_ok=True)
        cache = ROOT / ".cache" / "models"
        cache.mkdir(parents=True, exist_ok=True)
        config = build_config(self.models, cache_dir=cache, ctx_size=self.ctx_size)
        self.config_path.write_text(json.dumps(config, indent=2) + "\n")
        return self.config_path

    def start(self, ready_timeout_s: float = 120) -> "QvacServer":
        self.write_config()
        command = qvac_command() + [
            "serve", "--openai", "--no-default", "-c", str(self.config_path),
            "-H", "127.0.0.1", "-p", str(self.port),
            "--load-concurrency", "1", "--load-timeout", str(self.load_timeout_s * 1000),
        ]
        log = open(self.log_path, "ab")
        self.process = subprocess.Popen(command, cwd=self.workdir, stdout=log, stderr=subprocess.STDOUT,
                                        start_new_session=True)
        log.close()
        deadline = time.monotonic() + ready_timeout_s
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(f"qvac serve exited with {self.process.returncode}:\n{self.log_tail()}")
            try:
                with urllib.request.urlopen(self.base_url + "/models", timeout=2) as resp:
                    if resp.status == 200:
                        return self
            except OSError:
                time.sleep(0.5)
        self.stop()
        raise TimeoutError(f"qvac serve not ready after {ready_timeout_s}s:\n{self.log_tail()}")

    def stop(self):
        if self.process is None or self.process.poll() is not None:
            return
        try:
            os.killpg(self.process.pid, signal.SIGTERM)
            self.process.wait(timeout=15)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self.process.wait()

    def log_size(self) -> int:
        return self.log_path.stat().st_size if self.log_path.exists() else 0

    def log_since(self, offset: int) -> str:
        if not self.log_path.exists():
            return ""
        with open(self.log_path, "rb") as f:
            f.seek(offset)
            return f.read().decode("utf-8", "replace")

    def log_tail(self, lines: int = 30) -> str:
        if not self.log_path.exists():
            return ""
        return "\n".join(self.log_path.read_text(errors="replace").splitlines()[-lines:])

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()
