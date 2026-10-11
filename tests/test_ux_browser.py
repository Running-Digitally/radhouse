"""Browser regression cases with controlled API timing and the real app/CSP."""
import os
from pathlib import Path
import socket
import subprocess
import threading
import time

import pytest
import uvicorn

from radhouse.api.app import create_app

pytestmark = pytest.mark.postgres


def test_ux_regressions(service, alice):
    root = Path(__file__).resolve().parents[1]
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    origin = f"http://127.0.0.1:{sock.getsockname()[1]}"
    app = create_app(service, lambda _: alice, web_root=root / "web")
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.02)
        result = subprocess.run(["node", str(root / "web/test/ux-walkthrough.mjs")],
            env={**os.environ, "RADHOUSE_BROWSER_ORIGIN": origin,
                 "RADHOUSE_PLAYWRIGHT_MODULE": os.environ.get("RADHOUSE_PLAYWRIGHT_MODULE",
                     str(root / "web/node_modules/@playwright/test/index.mjs"))},
            capture_output=True, text=True, timeout=90)
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
