"""Small chat boundary and recovery proof with synthetic Hermes transport."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from radhouse.auth.local import LocalSession
from radhouse.chat.app import create_app
from radhouse.chat.service import ChatService
from radhouse.chat.store import ChatStore
from radhouse.domain.tasks import Rejected
from radhouse.integrations.hermes import HermesRunsClient


class SyntheticHermes:
    def __init__(self):
        self.requests = []
        self.runs = {}
        self.lose_ack = False
        self.disable_tools = True
        self.status = "running"
        self.output = "A synthetic reply."
        self.offline = False
        self.client = HermesRunsClient("http://127.0.0.1", "synthetic-only", transport=httpx.MockTransport(self.respond))

    def respond(self, request):
        if self.offline:
            raise httpx.ConnectError("synthetic failure", request=request)
        if request.url.path == "/v1/capabilities":
            return httpx.Response(200, json={"features": {"runs_idempotency": {"supported": True, "durable": True, "retention_seconds": 3600}, "runs_disable_tools": {"supported": self.disable_tools}}})
        if request.method == "POST":
            body = json.loads(request.content)
            key = request.headers["Idempotency-Key"]
            self.requests.append((key, body))
            replayed = key in self.runs
            run_id = self.runs.setdefault(key, "run_" + uuid4().hex)
            if self.lose_ack:
                self.lose_ack = False
                raise httpx.ReadError("synthetic lost acknowledgement", request=request)
            return httpx.Response(202, headers={"Idempotency-Replayed": "true" if replayed else "false"}, json={"run_id": run_id, "status": self.status if replayed else "started", "replayed": replayed})
        run_id = request.url.path.split("/")[-1]
        return httpx.Response(200, json={"run_id": run_id, "status": self.status, "output": self.output if self.status == "completed" else None})


class SyntheticAuth:
    cookie_name = "radhouse_session"
    secure_cookie = False

    def __init__(self):
        self.principal = "alice"
        self.active = True

    def health(self):
        pass

    def verify_origin(self, request):
        if request.headers.get("origin") != "http://127.0.0.1":
            raise Rejected("request_origin_denied", 403)

    def login(self, username, password, totp_code, source, *, remember_browser):
        if (username, password, totp_code) != ("alice", "synthetic-password", "123456"):
            raise Rejected("login_denied", 401)
        self.active = True
        return LocalSession("synthetic-cookie", "synthetic-csrf", self.principal, "alice", datetime.now(timezone.utc), "personal-alice:alice:radhouse", 1, "personal-alice")

    def session(self, request):
        if not self.active or request.cookies.get(self.cookie_name) != "synthetic-cookie":
            raise Rejected("authentication_required", 401)
        if request.method == "POST":
            self.verify_origin(request)
            if request.headers.get("x-radhouse-csrf") != "synthetic-csrf":
                raise Rejected("csrf_denied", 403)
        return LocalSession("synthetic-cookie", "synthetic-csrf", self.principal, "alice", datetime.now(timezone.utc), "personal-alice:alice:radhouse", 1, "personal-alice")

    refresh = session

    def revoke(self, request):
        self.session(request)
        self.active = False


@pytest.fixture
def chat(tmp_path):
    hermes = SyntheticHermes()
    store = ChatStore(tmp_path / "chat.sqlite3")
    service = ChatService(store, hermes.client, owner_id="alice", clock=lambda: 1000)
    yield service, hermes
    hermes.client.close()


def test_restart_keeps_session_transcript_and_run_without_redispatch(chat):
    service, hermes = chat
    request_id = str(uuid4())
    service.send("alice", request_id, "Hello")
    assert service.poll("alice")["turns"][0]["status"] == "running"
    reopened = ChatService(ChatStore(service.store.path), hermes.client, owner_id="alice", clock=lambda: 1001)
    hermes.status = "completed"
    assert reopened.poll("alice")["turns"][0]["output"] == "A synthetic reply."
    reopened.send("alice", request_id, "Hello")
    assert len(hermes.requests) == 1
    reopened.send("alice", str(uuid4()), "Continue")
    assert hermes.requests[0][1]["session_id"] == hermes.requests[1][1]["session_id"]
    assert all(body["disable_tools"] is True for _, body in hermes.requests)


def test_lost_ack_retries_saved_key_and_reads_completed_replay(chat):
    service, hermes = chat
    key = str(uuid4())
    hermes.lose_ack = True
    with pytest.raises(Rejected, match="assistant_unavailable"):
        service.send("alice", key, "Keep this")
    assert service.store.pending("alice")["error"] == "reply_dispatch_uncertain"
    hermes.status = "completed"
    reopened = ChatService(ChatStore(service.store.path), hermes.client, owner_id="alice", clock=lambda: 1001)
    reopened.send("alice", key, "Keep this")
    assert hermes.requests[0] == hermes.requests[1]
    assert len(hermes.runs) == 1
    assert reopened.poll("alice")["turns"][0]["output"] == "A synthetic reply."


def test_expired_unknown_dispatch_never_sends_again(chat):
    service, hermes = chat
    key = str(uuid4()); hermes.lose_ack = True
    with pytest.raises(Rejected): service.send("alice", key, "Uncertain")
    service.clock = lambda: 4540
    with pytest.raises(Rejected, match="reply_recovery_required"):
        service.send("alice", key, "Uncertain")
    with pytest.raises(Rejected, match="reply_pending"):
        service.send("alice", str(uuid4()), "Another")
    assert len(hermes.requests) == 1


def test_conflicting_replay_and_second_pending_message_are_refused(chat):
    service, hermes = chat
    key = str(uuid4()); service.send("alice", key, "Original")
    with pytest.raises(Rejected, match="message_conflict"): service.send("alice", key, "Changed")
    with pytest.raises(Rejected, match="reply_pending"): service.send("alice", str(uuid4()), "Second")
    assert len(hermes.requests) == 1


def test_concurrent_messages_reserve_only_one_pending_turn(chat):
    service, hermes = chat
    def send(_):
        try: service.send("alice", str(uuid4()), "Concurrent")
        except Rejected as error: return error.code
        return "accepted"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(send, range(2)))
    assert sorted(results) == ["accepted", "reply_pending"]
    assert len(hermes.runs) == 1


def test_tools_capability_missing_or_offline_never_dispatches(chat):
    service, hermes = chat
    hermes.disable_tools = False
    with pytest.raises(Rejected, match="chat_capability_unavailable"):
        service.send("alice", str(uuid4()), "Hello")
    hermes.offline = True
    with pytest.raises(Rejected, match="assistant_unavailable"):
        service.send("alice", str(uuid4()), "Hello")
    assert service.store.history("alice")["turns"] == []
    assert hermes.requests == []


@pytest.mark.parametrize("state,output,error", [("completed", " ", "empty_reply"), ("failed", None, "reply_failed"), ("interrupted", None, "reply_interrupted")])
def test_terminal_failure_is_honest_and_allows_next_turn(chat, state, output, error):
    service, hermes = chat
    service.send("alice", str(uuid4()), "Question")
    hermes.status, hermes.output = state, output
    turn = service.poll("alice")["turns"][0]
    assert turn["error"] == error and turn["output"] is None
    assert service.store.pending("alice") is None


def test_status_outage_keeps_saved_run_for_later_observation(chat):
    service, hermes = chat
    service.send("alice", str(uuid4()), "Question")
    hermes.offline = True
    with pytest.raises(Rejected, match="assistant_unavailable"): service.poll("alice")
    assert service.store.pending("alice")["error"] == "reply_status_unavailable"
    hermes.offline = False; hermes.status = "completed"
    assert service.poll("alice")["turns"][0]["output"]
    assert len(hermes.requests) == 1


def test_stale_observation_cannot_regress_completed_response(chat):
    service, hermes = chat
    service.send("alice", str(uuid4()), "Question")
    pending = service.store.pending("alice")
    hermes.status = "completed"; service.poll("alice")
    service.store.observe(pending, "running")
    assert service.store.history("alice")["turns"][0]["status"] == "completed"


def test_owner_is_server_bound_and_history_is_paged(chat):
    service, _hermes = chat
    with pytest.raises(Rejected, match="owner_access_required"): service.send("bob", str(uuid4()), "Secret")
    for i in range(55):
        turn = service.store.reserve("alice", str(uuid4()), str(i), 1000, 3600)
        service.store.attach(turn, "run_" + str(i), "running")
        service.store.observe(service.store.pending("alice"), "completed", output="reply")
    latest = service.store.history("alice")
    assert len(latest["turns"]) == 50 and latest["turns"][0]["text"] == "5"
    earlier = service.store.history("alice", latest["older_before"])
    assert [t["text"] for t in earlier["turns"]] == [str(i) for i in range(5)]
    assert earlier["older_before"] is None
    assert service.store.history("bob")["turns"] == []


def test_authentication_origin_csrf_and_public_contract(chat):
    service, hermes = chat; auth = SyntheticAuth()
    with TestClient(create_app(auth, service), base_url="http://127.0.0.1") as client:
        assert client.get("/chat/history").status_code == 401
        login = {"username": "alice", "password": "synthetic-password", "totp_code": "123456"}
        assert client.post("/auth/login", json=login).status_code == 403
        response = client.post("/auth/login", json=login, headers={"Origin": "http://127.0.0.1"})
        assert response.status_code == 200 and "HttpOnly" in response.headers["set-cookie"]
        assert response.headers["cache-control"] == "no-store"
        headers = {"Origin": "http://127.0.0.1", "X-Radhouse-CSRF": response.json()["csrf_token"]}
        body = {"request_id": str(uuid4()), "text": "Hello"}
        assert client.post("/chat/messages", json=body).status_code == 403
        assert client.post("/chat/messages", json=body, headers={**headers, "Origin": "https://evil.test"}).status_code == 403
        invalid = client.post("/chat/messages", json={**body, "session_id": "chosen"}, headers=headers)
        assert invalid.status_code == 422 and "Hello" not in invalid.text
        assert client.post("/chat/messages", json=body, headers=headers).status_code == 200
        assert "session_id" not in client.get("/chat/history").text
        auth.principal = "bob"
        assert client.get("/chat/history").status_code == 403
        assert client.get("/chat/reply").status_code == 403
        auth.principal = "alice"
        assert client.post("/auth/logout", json={}, headers=headers).status_code == 204
        assert client.get("/chat/history").status_code == 401
    assert len(hermes.requests) == 1


def test_store_refuses_public_file_and_foreign_schema(tmp_path):
    path = tmp_path / "public.sqlite3"; path.touch(mode=0o644)
    with pytest.raises(ValueError, match="private_regular_file"): ChatStore(path)
    path.chmod(0o600)
    import sqlite3
    with sqlite3.connect(path) as db: db.execute("PRAGMA user_version=99")
    with pytest.raises(ValueError, match="chat_schema_mismatch"): ChatStore(path)


def test_web_process_saves_reply_while_browser_is_closed(chat):
    import time
    service, hermes = chat
    with TestClient(create_app(SyntheticAuth(), service)):
        service.send("alice", str(uuid4()), "Finish while I am away")
        hermes.status = "completed"
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if service.store.history("alice")["turns"][0]["output"]:
                break
            time.sleep(0.05)
        assert service.store.history("alice")["turns"][0]["output"] == "A synthetic reply."
    assert len(hermes.runs) == 1
