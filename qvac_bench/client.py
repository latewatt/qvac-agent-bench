"""Minimal OpenAI-compatible chat client that keeps the raw response and timing."""
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field


@dataclass
class ChatResult:
    ok: bool
    status: int
    latency_s: float
    response: dict = field(default_factory=dict)
    error: str = ""

    @property
    def message(self) -> dict:
        try:
            return self.response["choices"][0]["message"] or {}
        except (KeyError, IndexError, TypeError):
            return {}

    @property
    def finish_reason(self) -> str:
        try:
            return self.response["choices"][0].get("finish_reason") or ""
        except (KeyError, IndexError, TypeError):
            return ""

    @property
    def tool_calls(self) -> list:
        return self.message.get("tool_calls") or []

    @property
    def usage(self) -> dict:
        return self.response.get("usage") or {}


class ChatClient:
    def __init__(self, base_url: str, api_key: str = "local", timeout: float = 600):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _request(self, method: str, path: str, payload: dict | None = None):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(self.base_url + path, data=data, method=method,
                                     headers={"Content-Type": "application/json",
                                              "Authorization": f"Bearer {self.api_key}"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return resp.status, json.load(resp)

    def models(self) -> list[dict]:
        return self._request("GET", "/models")[1].get("data", [])

    def chat(self, model: str, messages: list[dict], *, tools: list[dict] | None = None,
             tool_choice=None, parallel_tool_calls: bool | None = None,
             max_tokens: int = 512, temperature: float = 0.0) -> ChatResult:
        payload = {"model": model, "messages": messages, "max_tokens": max_tokens,
                   "temperature": temperature, "stream": False}
        if tools:
            payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
        if parallel_tool_calls is not None:
            payload["parallel_tool_calls"] = parallel_tool_calls
        started = time.monotonic()
        try:
            status, body = self._request("POST", "/chat/completions", payload)
            return ChatResult(True, status, time.monotonic() - started, body)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:2000]
            return ChatResult(False, exc.code, time.monotonic() - started, error=detail)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            return ChatResult(False, 0, time.monotonic() - started, error=repr(exc))
