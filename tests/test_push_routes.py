from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
import pytest

from radhouse.auth.local import LocalSession
from radhouse.chat.push import PushOutbox, PushResult
from radhouse.chat.push_routes import install_push
from radhouse.chat.store import ChatStore
from radhouse.domain.tasks import Rejected


@pytest.fixture
def fixture(tmp_path):
    app = FastAPI()
    @app.exception_handler(Rejected)
    async def rejected(_request, error):
        return JSONResponse({"error": error.code}, status_code=error.status)
    state = {"active": True}
    current = LocalSession("synthetic-session", "synthetic-csrf", "owner", "owner",
        datetime.now(timezone.utc), "conversation", 1, "project",
        datetime.now(timezone.utc) + timedelta(hours=1))
    def authenticate(request):
        if request.headers.get("authorization") != "synthetic-session":
            raise Rejected("authentication_required", 401)
        if request.method in {"PUT", "DELETE"} and request.headers.get("x-radhouse-csrf") != "synthetic-csrf":
            raise Rejected("csrf_denied", 403)
        return current
    def authorize(session):
        if session.principal_id != "owner":
            raise Rejected("owner_access_required", 403)
        return "owner"
    auth = SimpleNamespace(session=authenticate, notification_session_active=lambda *_: state["active"])
    service = SimpleNamespace(store=ChatStore(tmp_path / "chat.sqlite"), owner_id="owner", authorize=authorize)
    outbox = PushOutbox(tmp_path / "push.sqlite", Fernet.generate_key().decode())
    sent = []
    def send(*args):
        sent.append(args)
        return PushResult("sent")
    install_push(app, auth, service, outbox, send)
    headers = {"authorization": "synthetic-session", "x-radhouse-csrf": "synthetic-csrf"}
    return app, outbox, headers, state, sent, service


def test_device_routes_require_owner_session_csrf_and_bound_registration(fixture):
    app, outbox, headers, _, _, _ = fixture
    path = "/chat/push/devices/" + str(uuid4())
    body = {"platform": "ios", "token": "synthetic-fcm-token-0001"}
    with TestClient(app) as client:
        assert client.put(path, json=body).status_code == 401
        assert client.put(path, json=body, headers={"authorization": "synthetic-session"}).status_code == 403
        assert client.get("/chat/push/status", headers=headers).json() == {"available": True}
        assert client.put(path, json=body, headers=headers).json() == {"registered": True}
        with outbox.connection() as db:
            row = db.execute("SELECT * FROM devices").fetchone()
            assert row["owner"] == "owner"
            assert row["session_hash"] != "synthetic-session"
        assert client.delete(path, headers=headers).json() == {"registered": False}
        assert client.delete(path, headers=headers).status_code == 200


@pytest.mark.parametrize("body", [
    {"platform": "ios", "token": "synthetic-fcm-token-0001", "owner": "foreign"},
    {"platform": "web", "token": "synthetic-fcm-token-0001"},
    {"platform": "ios", "token": "small"},
    [],
])
def test_device_route_rejects_caller_identity_and_invalid_body(fixture, body):
    app, _, headers, _, _, _ = fixture
    path = "/chat/push/devices/" + str(uuid4())
    with TestClient(app) as client:
        assert client.put(path, json=body, headers=headers).status_code == 422


def test_large_body_malformed_json_and_revoked_session(fixture):
    app, _, headers, state, _, _ = fixture
    path = "/chat/push/devices/" + str(uuid4())
    with TestClient(app) as client:
        assert client.put(path, content="x" * 8193, headers=headers).status_code == 413
        assert client.put(path, content="not json", headers=headers).status_code == 422
        state["active"] = False
        body = {"platform": "ios", "token": "synthetic-fcm-token-0001"}
        assert client.put(path, json=body, headers=headers).status_code == 401


def test_observer_dispatches_durable_completion_without_a_mobile_poll(fixture):
    import time
    app, _, headers, _, sent, service = fixture
    with TestClient(app) as client:
        path = "/chat/push/devices/" + str(uuid4())
        body = {"platform": "ios", "token": "synthetic-fcm-token-0001"}
        assert client.put(path, json=body, headers=headers).status_code == 200
        saved = service.store.reserve("owner", str(uuid4()), "Private message", time.time())
        with service.store.connection() as db:
            db.execute("UPDATE turns SET status='completed',output='Private reply' WHERE seq=?", (saved["seq"],))
        deadline = time.monotonic() + 5
        while not sent and time.monotonic() < deadline:
            time.sleep(0.02)
    assert len(sent) == 1
    assert sent[0][2]["request_id"] == saved["request_id"]
