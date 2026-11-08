import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest


class FakeServer:
    """An OpenAI-compatible endpoint that answers from a queue of scripted replies."""

    def __init__(self):
        self.replies = []
        self.requests = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, status, body):
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path.startswith("/v1/models"):
                    self._send(200, {"object": "list", "data": [{"id": "fake", "object": "model"}]})
                else:
                    self._send(404, {"error": "not found"})

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                server.requests.append(json.loads(self.rfile.read(length)))
                status, body = server.replies.pop(0) if server.replies else (500, {"error": "no reply queued"})
                self._send(status, body)

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.base_url = f"http://127.0.0.1:{self.httpd.server_address[1]}/v1"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def reply_calls(self, *calls, content=None):
        tool_calls = [{"id": f"call_{i}", "type": "function",
                       "function": {"name": name, "arguments": args if isinstance(args, str) else json.dumps(args)}}
                      for i, (name, args) in enumerate(calls)]
        message = {"role": "assistant", "content": content, "tool_calls": tool_calls or None}
        self.replies.append((200, {"choices": [{"message": message, "finish_reason": "tool_calls" if calls else "stop"}],
                                   "usage": {"prompt_tokens": 100, "completion_tokens": 20}}))

    def reply_text(self, text):
        self.reply_calls(content=text)


@pytest.fixture
def fake():
    server = FakeServer()
    yield server
    server.httpd.shutdown()
