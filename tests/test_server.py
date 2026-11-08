import json
import sys

from qvac_bench.server import QvacServer, build_config, count_tool_errors


def test_config_turns_on_tools_and_disables_thinking(tmp_path):
    models = {"a": {"model": "QWEN3_5_4B_MULTIMODAL_Q4_K_M"}, "b": {"model": "QWEN3_8B_INST_Q4_K_M", "ctx_size": 4096}}
    config = build_config(models, cache_dir=tmp_path)
    entries = config["serve"]["models"]
    assert entries["a"]["default"] and not entries["b"]["default"]
    assert entries["a"]["config"]["tools"] is True
    assert entries["a"]["config"]["reasoning_budget"] == 0
    assert entries["b"]["config"]["ctx_size"] == 4096
    assert config["cacheDirectory"] == str(tmp_path)


def test_tool_error_counting():
    log = ("← 200 POST /v1/chat/completions (812ms) toolerrors=1 (PARSE_ERROR)\n"
           "← 200 POST /v1/chat/completions (90ms)\n"
           "... toolerrors=2 (PARSE_ERROR)\n")
    assert count_tool_errors(log) == 3
    assert count_tool_errors("nothing here") == 0


def test_server_lifecycle_with_a_stand_in_cli(tmp_path, monkeypatch):
    """Drive QvacServer with a tiny Python script that speaks the same CLI and /v1/models."""
    stand_in = tmp_path / "fake_qvac.py"
    stand_in.write_text(
        "import json,sys\n"
        "from http.server import BaseHTTPRequestHandler,HTTPServer\n"
        "args=sys.argv[1:]; assert args[:3]==['serve','--openai','--no-default'], args\n"
        "json.load(open(args[args.index('-c')+1]))\n"
        "port=int(args[args.index('-p')+1])\n"
        "class H(BaseHTTPRequestHandler):\n"
        "  def log_message(self,*a): print('GET', self.path, 'toolerrors=1 (PARSE_ERROR)', flush=True)\n"
        "  def do_GET(self):\n"
        "    b=json.dumps({'data':[]}).encode(); self.send_response(200); self.send_header('Content-Length',str(len(b))); self.end_headers(); self.wfile.write(b)\n"
        "HTTPServer(('127.0.0.1',port),H).serve_forever()\n")
    monkeypatch.setenv("QVAC_CMD", f"{sys.executable} {stand_in}")
    srv = QvacServer(tmp_path / "run", {"m": {"model": "X"}}, port=_free_port())
    with srv:
        assert json.loads(srv.config_path.read_text())["serve"]["models"]["m"]["model"] == "X"
        offset = srv.log_size()
        import urllib.request
        urllib.request.urlopen(srv.base_url + "/models").read()
        import time; time.sleep(0.2)
        assert count_tool_errors(srv.log_since(offset)) == 1
    assert srv.process.poll() is not None


def _free_port():
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
