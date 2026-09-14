"""Real browser, API, PostgreSQL and signed relay bridge; synthetic model only."""
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
from tests.test_buzz_conversations import bridge, incoming
from tests.test_local_reauthentication import local_client

pytestmark = pytest.mark.postgres


def test_conversation_browser_reconnect_and_lost_send(bridge, local_client, service, clock, tmp_path):
    root = Path(__file__).resolve().parents[1]
    cycle, relay, owner = bridge
    _, auth, totp, password = local_client
    clock.now = datetime.now(timezone.utc)
    with service.store.transaction() as tx:
        tx._connection.execute("UPDATE bots SET display_name='Researcher' WHERE bot_id=%s", (cycle.link.bot_id,))
    relay["messages"] = [incoming(cycle, owner, "Compare two morning routines.")]
    cycle.ingress()
    with service.store.transaction() as tx:
        original_id = tx.tasks()[0].task_id
    service.run(original_id)
    cycle.egress()
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    origin = f"http://127.0.0.1:{sock.getsockname()[1]}"
    auth._expected_origin = origin
    auth.secure_cookie = False
    app = create_app(service, auth.auth_context, local_auth=auth, web_root=root / "web")
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
    server_thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    stop = threading.Event()
    errors = []

    def coordinate():
        while not stop.wait(0.2):
            try:
                cycle.ingress()
                for task_id in service.coordination_candidates(10):
                    service.advance(task_id, "conversation-fixture")
                cycle.egress()
            except Exception as error:
                errors.append(type(error).__name__)
                return

    worker = threading.Thread(target=coordinate, daemon=True)
    server_thread.start()
    worker.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.02)
        result = subprocess.run(["node", str(root / "web/test/conversation-walkthrough.mjs")], env={**os.environ,
            "RADHOUSE_PLAYWRIGHT_MODULE": os.environ.get("RADHOUSE_PLAYWRIGHT_MODULE", str(root / "web/node_modules/@playwright/test/index.mjs")),
            "RADHOUSE_BROWSER_ORIGIN": origin, "RADHOUSE_TEST_PASSWORD": password,
            "RADHOUSE_TEST_TOTP": totp.at(clock()), "RADHOUSE_SCREENSHOT": str(tmp_path / "conversation.png")},
            capture_output=True, text=True, timeout=90)
        assert result.returncode == 0, result.stdout + result.stderr
        assert not errors, errors
        with service.store.transaction() as tx:
            tasks = tx.tasks()
            assert len(tasks) == 2
            followup = next(task for task in tasks if task.task_id != original_id)
            assert followup.follows_task_id == original_id
            assert followup.disable_tools
            assert followup.files[0].content == "A quiet walk before breakfast."
        assert any("via Radhouse" in event["content"] for event in relay["published"].values())
        print("CONVERSATION_SCREENSHOT", tmp_path / "conversation.png")
    finally:
        stop.set()
        server.should_exit = True
        worker.join(timeout=5)
        server_thread.join(timeout=5)
        sock.close()
