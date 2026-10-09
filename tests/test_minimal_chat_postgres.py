"""Reused real auth plus actual browser; owned database and synthetic model only."""
from datetime import datetime, timezone
import os
from pathlib import Path
import socket
import subprocess
import threading
import time
from uuid import uuid4

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pyotp
import pytest
import uvicorn

from radhouse.auth.local import LocalAuthService, provision_local_user
from radhouse.chat.app import create_app
from radhouse.chat.agent_profile import DEFAULT_PROFILE
from radhouse.chat.service import ChatService
from radhouse.chat.store import ChatStore
from tests.test_minimal_chat import SyntheticHermes

pytestmark = pytest.mark.postgres


@pytest.fixture
def real_chat(store, clock, tmp_path):
    run_id = os.environ["RADHOUSE_VS0_RUN_ID"]
    dsn = os.environ["RADHOUSE_VS0_DSN"]
    common = dict(expected_database=f"radhouse_vs0_{run_id}", deployment_id=f"fixture-{run_id}", encryption_key=Fernet.generate_key().decode())
    secret = pyotp.random_base32(); password = "synthetic-minimal-chat-password"
    clock.now = datetime.now(timezone.utc)
    provision_local_user(dsn, **common, principal_id="alice", username="alice", role="operator",
        password=password, totp_secret=secret, project_id="personal-alice", project_name="My work",
        bot_id="bot-alpha", bot_display_name="Assistant", bot_role_name="Assistant", provider_binding="fake-local", now=clock())
    auth = LocalAuthService(dsn, **common, expected_origin="http://127.0.0.1", secure_cookie=False, clock=clock)
    auth._test_next_totp_code = pyotp.TOTP(secret).at(clock().timestamp()+30)
    hermes = SyntheticHermes(); hermes.status = "completed"
    service = ChatService(ChatStore(tmp_path / "chat.sqlite3"), hermes.client, owner_id="alice")
    yield auth, service, hermes, pyotp.TOTP(secret).at(clock()), password
    hermes.client.close()


def test_real_auth_cookie_csrf_logout_and_schema_unchanged(real_chat, store):
    auth, service, hermes, code, password = real_chat
    with TestClient(create_app(auth, service), base_url="http://127.0.0.1") as client:
        assert client.get("/chat/history").status_code == 401
        assert client.get("/chat/agent-profile").status_code == 401
        response = client.post("/auth/login", json={"username":"alice","password":password,"totp_code":code}, headers={"Origin":"http://127.0.0.1"})
        assert response.status_code == 200
        token = response.json()["csrf_token"]
        headers = {"Origin":"http://127.0.0.1", "X-Radhouse-CSRF":token}
        assert client.get("/chat/agent-profile").json() == DEFAULT_PROFILE
        profile = {**DEFAULT_PROFILE, "name": "Saved with real auth"}
        assert client.post("/chat/agent-profile", json=profile, headers={"Origin":"http://127.0.0.1"}).status_code == 403
        assert client.post("/chat/agent-profile", json=profile, headers={**headers, "Origin":"https://evil.test"}).status_code == 403
        assert client.post("/chat/agent-profile", json=profile, headers=headers).json() == {**profile, "revision": 1}
        file_path = f"/chat/files/{uuid4()}?name=note.txt"
        assert client.put(file_path,content=b"private note",headers={"Origin":"http://127.0.0.1"}).status_code == 403
        assert client.put(file_path,content=b"private note",headers={**headers,"Origin":"https://evil.test"}).status_code == 403
        assert client.put(file_path,content=b"private note",headers=headers).status_code == 200
        body = {"request_id":str(uuid4()),"text":"A real authenticated synthetic conversation"}
        assert client.post("/chat/messages", json=body, headers={"Origin":"http://127.0.0.1"}).status_code == 403
        assert client.post("/chat/messages", json=body, headers={**headers, "Origin":"https://evil.test"}).status_code == 403
        assert client.post("/chat/messages", json=body, headers=headers).status_code == 200
        assert client.get("/chat/reply").json()["turns"][0]["output"] == "A synthetic reply."
        assert client.post("/auth/logout", json={}, headers=headers).status_code == 204
        assert client.get("/chat/history").status_code == 401
        assert client.get("/chat/agent-profile").status_code == 401
    with store.transaction() as tx:
        assert tx._connection.execute("SELECT schema_version FROM radhouse_metadata").fetchone()["schema_version"] == 7
    assert len(hermes.runs) == 1


def test_actual_browser_login_reload_lost_response_and_text_rendering(real_chat, tmp_path):
    auth, service, hermes, code, password = real_chat
    service.transcriber = type("Speech",(),{"transcribe":lambda _,a:"A simulated voice note transcript."})()
    from tests.test_chat_attachments import PNG, pdf, office, wav
    for name,data in [("diagram.png",PNG),("plan.pdf",pdf()),("plan.docx",office(".docx")),("voice.wav",wav()),("notes.txt",b"A simple plan")]:
        (tmp_path / name).write_bytes(data)
    with (tmp_path / "large.bin").open("wb") as large:
        for _ in range(36): large.write(b"\x00original transfer" * 65536)
    hermes.output = "Here is your saved reply. <script>window.chatInjected=true</script>\n\n**Small step**\n\n- Try one thing\n- Keep it simple\n\n```python\nprint('hello')\n```\n\n[Guide](https://example.com/guide) [Unsafe](javascript:alert(1))"
    sock = socket.socket(); sock.bind(("127.0.0.1", 0))
    origin = f"http://127.0.0.1:{sock.getsockname()[1]}"
    auth._expected_origin = origin
    server = uvicorn.Server(uvicorn.Config(create_app(auth, service), log_level="error", access_log=False))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    root = Path(__file__).resolve().parents[1]
    try:
        for _ in range(100):
            if server.started: break
            time.sleep(0.02)
        result = subprocess.run(["node", str(root / "tests/minimal-chat-browser.mjs")], env={**os.environ,
            "RADHOUSE_PLAYWRIGHT_MODULE": str(root / "web/node_modules/@playwright/test/index.mjs"),
            "RADHOUSE_BROWSER_ORIGIN":origin,"RADHOUSE_TEST_PASSWORD":password,"RADHOUSE_TEST_TOTP":code,
            "RADHOUSE_TEST_NEXT_TOTP":auth._test_next_totp_code,
            "RADHOUSE_SCREENSHOT":str(tmp_path / "minimal-chat.png"),"RADHOUSE_ATTACHMENT_FIXTURES":str(tmp_path)}, capture_output=True, text=True, timeout=90)
        assert result.returncode == 0, result.stdout + result.stderr
        assert len(hermes.runs) == 8
        assert "A small plan" in hermes.requests[4][1]["input"][0]["content"][0]["text"]
        assert "simulated voice note" in hermes.requests[4][1]["input"][0]["content"][0]["text"]
        assert hermes.requests[4][1]["input"][0]["content"][1]["type"] == "image_url"
        assert 'large.bin' in hermes.requests[6][1]['input']
        assert 'original saved, not read' in hermes.requests[6][1]['input']
        assert len({body["session_id"] for _, body in hermes.requests}) == 1
        print("MINIMAL_CHAT_SCREENSHOT", tmp_path / "minimal-chat.png")
    finally:
        server.should_exit = True; thread.join(timeout=5); sock.close()
