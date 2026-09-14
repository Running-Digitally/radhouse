"""Operator guidance through the real web API and owned database; no model calls."""
from dataclasses import replace
from datetime import datetime, timezone
import os
from pathlib import Path
import socket
import subprocess
import threading
import time

import pytest
import uvicorn

from radhouse.api.app import create_app
from radhouse.domain.tasks import RuntimeResult
from tests.test_local_reauthentication import local_client
from tests.test_runtime_controls import receipt

pytestmark = pytest.mark.postgres


def test_guidance_focus_outcomes_and_reconnect(local_client, service, fake_work, alice, envelope, start, clock):
    root = Path(__file__).resolve().parents[1]
    _, auth, totp, password = local_client
    clock.now = datetime.now(timezone.utc)
    fake_work.result = lambda *_: RuntimeResult("running", guidance_receipts=())
    task = service.run(service.admit(alice, envelope(), replace(start, brief="Compare the synthetic references in several steps.")).task_id)
    values = []
    def steer(task, run, text, control_id):
        values.append(receipt(run, control_id, text))
        return values[-1]
    fake_work.steer = steer
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    origin = f"http://127.0.0.1:{sock.getsockname()[1]}"
    auth._expected_origin = origin
    auth.secure_cookie = False
    app = create_app(service, auth.auth_context, local_auth=auth, web_root=root / "web")

    @app.post("/_fixture/finish-guided-response")
    def finish():
        assert len(values) == 1
        applied = replace(values[0], state="applied", revision=2, checkpoint_id="checkpoint-1", api_request_id="request-2")
        fake_work.result = lambda *_: RuntimeResult("completed", "The synthetic result follows the cost emphasis.", guidance_receipts=(applied,))
        service.recover(task.task_id)
        return {"finished": True}

    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.02)
        result = subprocess.run(["node", str(root / "web/test/guidance-walkthrough.mjs")], env={**os.environ,
            "RADHOUSE_PLAYWRIGHT_MODULE": str(root / "web/node_modules/@playwright/test/index.mjs"),
            "RADHOUSE_BROWSER_ORIGIN": origin, "RADHOUSE_TEST_PASSWORD": password,
            "RADHOUSE_TEST_TOTP": totp.at(clock())}, capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stdout + result.stderr
        assert len(values) == 1 and fake_work.start_count == 1
        with service.store.transaction() as tx:
            done = tx.task(task.task_id)
            assert done.guidance[0]["application_state"] == "applied"
            assert not done.disable_tools and tx.publication(task.task_id) is None
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
