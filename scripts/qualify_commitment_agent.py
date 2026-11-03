"""Qualify the actual native agent against an owned, synthetic loopback provider.

No owner profile or real provider credentials. Source is cloned into disposable
storage, the exact base overlay is applied, and outbound sockets are restricted
to loopback in the child. This is runtime qualification, not model-quality evidence.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


ROOT = Path(__file__).resolve().parents[1]


def qualify(source, dependencies=None):
    pin = json.loads((ROOT / "runtime/hermes/source-lock.json").read_text())["upstream_commit"]
    actual = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if actual != pin:
        raise ValueError("qualification_source_mismatch")
    with tempfile.TemporaryDirectory(prefix="radhouse-commitment-native-") as temporary:
        temporary = Path(temporary)
        native, home, support = (temporary / name for name in ("native", "home", "support"))
        home.mkdir(mode=0o700)
        support.mkdir()
        subprocess.run(["git", "-c", "advice.detachedHead=false", "clone", "--quiet", "--shared", str(source), str(native)], check=True, timeout=60)
        spec = importlib.util.spec_from_file_location("qualification_base_overlay", ROOT / "runtime/hermes/base_overlay.py")
        overlay = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(overlay)
        for name, contents in overlay.render(native).items():
            path = native / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(contents)
        (home / "memories").mkdir()
        for name in ("SOUL.md", "AGENTS.md", "memories/MEMORY.md", "memories/USER.md"):
            (home / name).write_text("UNSCOPED_CONTEXT_CANARY_MUST_NOT_BE_SENT\n")
        (support / "sitecustomize.py").write_text('''import socket
original = socket.getaddrinfo
def bounded(host, *args, **kwargs):
    if host not in ('127.0.0.1', 'localhost', '::1', b'127.0.0.1'):
        raise OSError('qualification blocks non-loopback network')
    return original(host, *args, **kwargs)
socket.getaddrinfo = bounded
connect = socket.socket.connect
def bounded_connect(self, address):
    if self.family in (socket.AF_INET, socket.AF_INET6) and address[0] not in ('127.0.0.1', '::1'):
        raise OSError('qualification blocks non-loopback network')
    return connect(self, address)
socket.socket.connect = bounded_connect
''')
        requests = []
        class Provider(BaseHTTPRequestHandler):
            def log_message(self, *_):
                # Keep the qualification provider's synthetic HTTP access log quiet.
                pass
            def do_POST(self):
                size = int(self.headers.get("Content-Length", "0"))
                if size > 1000000 or self.path != "/v1/chat/completions":
                    self.send_error(400)
                    return
                request = json.loads(self.rfile.read(size))
                requests.append(request)
                content = '{"suggestions":[]}'
                base = {"id":"synthetic-completion", "created":1, "model":"fixture-model"}
                if request.get("stream"):
                    frames = [
                        {**base, "object":"chat.completion.chunk", "choices":[{"index":0,"delta":{"role":"assistant","content":content},"finish_reason":None}]},
                        {**base, "object":"chat.completion.chunk", "choices":[{"index":0,"delta":{},"finish_reason":"stop"}]},
                    ]
                    body = ("".join("data: "+json.dumps(frame)+"\n\n" for frame in frames)+"data: [DONE]\n\n").encode()
                    media = "text/event-stream"
                else:
                    body = json.dumps({**base, "object":"chat.completion", "choices":[{"index":0,
                        "message":{"role":"assistant","content":content},"finish_reason":"stop"}],
                        "usage":{"prompt_tokens":100,"completion_tokens":5,"total_tokens":105}}).encode()
                    media = "application/json"
                self.send_response(200)
                self.send_header("Content-Type",media)
                self.send_header("Content-Length",str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        server = ThreadingHTTPServer(("127.0.0.1",0),Provider)
        thread = threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            endpoint = f"http://127.0.0.1:{server.server_port}/v1"
            (home / "config.yaml").write_text("model:\n  provider: custom\n  default: fixture-model\n  base_url: "+endpoint+"\n  context_length: 65536\n")
            (home / ".env").write_text("OPENAI_API_KEY=synthetic-provider-key\nOPENAI_BASE_URL="+endpoint+"\n")
            driver = support / "driver.py"
            driver.write_text('''import contextlib, importlib.util, json, sys
spec=importlib.util.spec_from_file_location('qualified_worker',sys.argv[1])
worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(worker)
with contextlib.redirect_stdout(sys.stderr):
    output=worker.native_review('Return only {"suggestions":[]} for this synthetic empty review.',
        {'provider':'custom','model':'fixture-model','hermes_root':sys.argv[2]})
print(json.dumps({'output':output}))
''')
            paths = [support, native] + ([Path(dependencies)] if dependencies else [])
            env = {key:os.environ[key] for key in ("PATH","LANG","TMPDIR") if key in os.environ}
            env.update(HERMES_HOME=str(home), HERMES_TEST_ISOLATION=str(home),
                       PYTHONPATH=os.pathsep.join(map(str,paths)))
            result = subprocess.run([sys.executable,str(driver),str(ROOT / "runtime/hermes/commitment_worker.py"),str(native)],
                env=env,cwd=home,capture_output=True,text=True,timeout=180)
            if result.returncode:
                # All inputs are synthetic; bounded diagnostics help repair the qualifier.
                raise RuntimeError("native qualification failed:\n"+result.stderr[-5000:])
            value = json.loads(result.stdout)
            if json.loads(value["output"]) != {"suggestions":[]} or not requests:
                raise ValueError("qualification_result_mismatch")
            if any(request.get("tools") or request.get("functions") for request in requests):
                raise ValueError("qualification_exposed_tools")
            if "UNSCOPED_CONTEXT_CANARY" in json.dumps(requests):
                raise ValueError("qualification_loaded_unscoped_context")
            return {"status":"passed","native_commit":pin,"provider_requests":len(requests),
                    "tools_exposed":0,"unscoped_context_canaries_sent":False,"result":"quiet_success"}
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source",type=Path)
    parser.add_argument("--dependencies",type=Path)
    arguments = parser.parse_args()
    print(json.dumps(qualify(arguments.source,arguments.dependencies),sort_keys=True))
