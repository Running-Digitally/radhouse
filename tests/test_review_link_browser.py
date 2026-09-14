"""Real browser login and MFA recovery preserve an authenticated review target."""
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
from tests.test_review_links import review_link, enrollment, bridge
from tests.test_local_reauthentication import local_client

pytestmark = pytest.mark.postgres


def test_review_link_login_reauthentication_publication(review_link, local_client, service, clock):
    _, done, configured, state, link = review_link
    _, auth, totp, password = local_client
    root = Path(__file__).resolve().parents[1]
    clock.now = datetime.now(timezone.utc)
    with service.store.transaction() as tx:
        token = service.review_links.issue(tx, link, done).split("#review=")[1]
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    origin = f"http://127.0.0.1:{sock.getsockname()[1]}"
    auth._expected_origin = origin
    auth.secure_cookie = False
    app = create_app(service, auth.auth_context, local_auth=auth, web_root=root / "web")

    @app.post("/_fixture/assurance-expires")
    def expire_synthetic_assurance():
        clock.advance(minutes=11)
        return {"totp": totp.at(clock())}

    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
    worker = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    worker.start()
    try:
        for _ in range(100):
            if server.started: break
            time.sleep(0.02)
        result = subprocess.run(["node", str(root / "web/test/review-link-walkthrough.mjs")], env={**os.environ,
            "RADHOUSE_PLAYWRIGHT_MODULE": os.environ.get("RADHOUSE_PLAYWRIGHT_MODULE", str(root / "web/node_modules/@playwright/test/index.mjs")),
            "RADHOUSE_BROWSER_ORIGIN": origin, "RADHOUSE_TEST_PASSWORD": password,
            "RADHOUSE_TEST_TOTP": totp.at(clock()), "RADHOUSE_TEST_LOCATOR": token,
            "RADHOUSE_TEST_TASK": done.task_id}, capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stdout + result.stderr
        assert configured.run("egress")["error_code"] is None
        with service.store.transaction() as tx:
            assert tx.publication(done.task_id).channel == "radhouse"
            assert len(tx.tasks()) == 1
            assert len([r for r in tx.conversation_history(link.link_id) if r["message"].state == "publication"]) == 1
    finally:
        server.should_exit = True
        worker.join(timeout=5)
        sock.close()
