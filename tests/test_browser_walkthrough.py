"""Real browser and PostgreSQL walkthrough inside the owned fixture."""
from datetime import datetime, timezone
import os
from pathlib import Path
import socket
import subprocess
import threading
import time

from fastapi import Request
from fastapi.responses import HTMLResponse
import httpx
import pytest
import uvicorn

from radhouse.api.app import create_app
from radhouse.channels.nostr import encoded, sha256
from tests.test_local_reauthentication import local_client

pytestmark = pytest.mark.postgres


def test_web_review_and_followup_walkthrough(local_client, service, fake_work, clock, tmp_path):
    root = Path(__file__).resolve().parents[1]
    playwright = os.environ.get("RADHOUSE_PLAYWRIGHT_MODULE", str(root / "web/node_modules/@playwright/test/index.mjs"))
    assert Path(playwright).is_file(), "Run npm ci in web/ and install Playwright Chromium before verification"
    _, auth, totp, password = local_client
    fake_work.result_content = """# Useful financial report

**Revenue** exceeds costs.

| Measure | Value |
| --- | ---: |
| Revenue | 42 |
| Costs | 12 |

<script>window.radhouseUnsafe = true</script>
[Unsafe link](javascript:alert(1))
![External image](https://example.invalid/private-result.png)
"""
    clock.now = datetime.now(timezone.utc)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    origin = f"http://127.0.0.1:{sock.getsockname()[1]}"
    auth._expected_origin = origin
    auth.secure_cookie = False  # Only this owned loopback fixture.
    app = create_app(service, auth.auth_context, local_auth=auth, web_root=root / "web")
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
    server_thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    stop = threading.Event()
    def coordinate():
        while not stop.wait(0.2):
            for task_id in service.coordination_candidates(10): service.advance(task_id, "browser-fixture")
    worker = threading.Thread(target=coordinate, daemon=True)
    server_thread.start(); worker.start()
    try:
        for _ in range(100):
            if server.started: break
            time.sleep(0.02)
        result = subprocess.run(["node", str(root / "web/test/browser-walkthrough.mjs")], env={**os.environ,
            "RADHOUSE_PLAYWRIGHT_MODULE": playwright,
            "RADHOUSE_BROWSER_ORIGIN": origin, "RADHOUSE_TEST_PASSWORD": password,
            "RADHOUSE_TEST_TOTP": totp.at(clock()), "RADHOUSE_SCREENSHOT": str(tmp_path / "operator.png")},
            capture_output=True, text=True, timeout=90)
        assert result.returncode == 0, result.stdout + result.stderr
        with service.store.transaction() as tx:
            tasks = tx.tasks()
            assert len(tasks) == 2
            followup = next(task for task in tasks if task.follows_task_id)
            original = next(task for task in tasks if not task.follows_task_id)
            assert followup.follows_task_id == original.task_id
            assert tx.publication(original.task_id).channel == "radhouse"
    finally:
        stop.set(); server.should_exit = True
        worker.join(timeout=5); server_thread.join(timeout=5); sock.close()
