"""A real shared file requires the scoped callback, not a filename in prose."""
from concurrent.futures import ThreadPoolExecutor
import json
import sys
from types import ModuleType, SimpleNamespace
from uuid import NAMESPACE_URL, uuid4, uuid5
import hashlib

from fastapi.testclient import TestClient
import httpx
import pytest

from radhouse.chat.app import create_app
from radhouse.chat.document_bridge import DocumentBridge, FileShareCall
from radhouse.chat.service import ChatService
from radhouse.chat.store import ChatStore
from radhouse.domain.tasks import Rejected
from tests.test_document_bridge import Runtime, complete, context, original, token
from tests.test_minimal_chat import SyntheticAuth


class SharingRuntime(Runtime):
    sharing = True
    sharing_version = 1

    def respond(self, request):
        response = super().respond(request)
        if request.url.path == "/v1/capabilities":
            value = response.json()
            value["features"]["runs_disable_tools"] = {"supported": True}
            value["features"]["runs_file_share"] = {"supported": self.sharing, "version": self.sharing_version}
            return httpx.Response(200, json=value)
        return response


@pytest.fixture
def sharing(tmp_path):
    runtime, store, now = SharingRuntime(), ChatStore(tmp_path / "chat.sqlite3"), [1000]
    service = ChatService(store, runtime.client, owner_id="alice", clock=lambda: now[0], document_access=True)
    bridge = DocumentBridge(store, runtime.client, owner_id="alice", clock=lambda: now[0])
    service.send("alice", str(uuid4()), "Make a report")
    yield service, runtime, bridge, now
    runtime.client.close()


def call(runtime, *, name="report.md", content="# Report\nA real shared result: café.\n"):
    identity = context(runtime)
    return FileShareCall(run_id=identity.run_id, session_id=identity.session_id,
        dispatch_key=identity.dispatch_key, name=name, content=content)


def test_shared_callback_publishes_real_bytes_history_library_and_future_scope(sharing):
    service, runtime, bridge, _ = sharing
    assert runtime.requests[0]["allowed_tools"] == ["document_search", "document_read", "file_share"]
    assert "file_share(name, content)" in runtime.requests[0]["input"]
    before = bridge.grant(token(runtime))["files"]
    result = bridge.share(token(runtime), call(runtime))
    assert result["kind"] == "file"
    item = result["file"]
    assert item["kind"] == "text" and item["source"] == "assistant"
    assert service.store.upload("alice", item["file_id"]).data.read_bytes() == call(runtime).content.encode()
    history = service.store.history("alice")["turns"][0]
    assert history["shared_files"] == [item] and history["attachments"] == []
    assert service.store.library("alice", source="assistant")["files"] == [item]
    assert not service.store.library("alice", source="user")["files"]
    assert not service.store.library("bob")["files"]
    assert bridge.grant(token(runtime))["files"] == before == {}  # Never widen the current grant.
    unsent = original(service.store, name="not-sent.txt")
    complete(service, runtime)
    service.send("alice", str(uuid4()), "Read the report")
    scope = bridge.grant(token(runtime))
    assert set(scope["files"]) == {item["file_id"]} and unsent.file_id not in scope["files"]
    passage = bridge.execute(token(runtime), context(runtime, file_id=item["file_id"]), "read")
    assert "café" in "".join(p["text"] for p in passage["passages"])


def test_http_share_download_range_and_owner_authorization(sharing):
    service, runtime, bridge, _ = sharing
    auth = SyntheticAuth()
    client = TestClient(create_app(auth, service, documents=bridge))
    try:
        request = call(runtime)
        response = client.post("/internal/documents/share", json=request.model_dump(),
            headers={"Authorization": "Bearer " + token(runtime)})
        assert response.status_code == 200
        item = response.json()["file"]
        assert "document_scope_token" not in json.dumps(response.json())
        assert client.get(item["download_url"]).status_code == 401
        client.cookies.set(auth.cookie_name, "synthetic-cookie")
        download = client.get(item["download_url"])
        assert download.content == request.content.encode()
        assert download.headers["x-content-type-options"] == "nosniff"
        assert download.headers["content-disposition"].startswith("attachment;")
        assert client.get(item["download_url"], headers={"Range": "bytes=0-7"}).content == b"# Report"
        auth.principal = "bob"
        assert client.get(item["download_url"]).status_code == 403
        assert client.get("/chat/library").status_code == 403
    finally:
        client.close()


def test_share_is_idempotent_across_concurrent_retries_and_restart(sharing):
    service, runtime, bridge, now = sharing
    request, scope = call(runtime), token(runtime)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: bridge.share(scope, request), range(2)))
    assert results[0] == results[1]
    reopened = DocumentBridge(ChatStore(service.store.path), runtime.client, owner_id="alice", clock=lambda: now[0])
    assert reopened.share(scope, request) == results[0]
    with service.store.connection() as db:
        assert db.execute("SELECT count(*) FROM assistant_files").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM uploads").fetchone()[0] == 1
    assert len(tuple(service.store.files_path.iterdir())) == 1
    changed = bridge.share(scope, request.model_copy(update={"content": "A revised result"}))
    assert changed["file"]["file_id"] != results[0]["file"]["file_id"]
    assert service.store.upload("alice", results[0]["file"]["file_id"]).data.read_bytes() == request.content.encode()


def test_share_conflicting_existing_upload_is_never_overwritten(sharing):
    service, runtime, bridge, _ = sharing
    request = call(runtime)
    digest = hashlib.sha256(request.content.encode()).hexdigest()
    file_id = str(uuid5(NAMESPACE_URL, json.dumps(
        ["radhouse.shared-file.v1", request.run_id, request.name, digest], separators=(",", ":"))))
    stream, path = service.store.begin_upload("alice", file_id, request.name)
    with stream: stream.write(request.content.encode())
    service.store.commit_upload("alice", file_id, request.name, path, "text/plain", "text", digest, len(request.content.encode()))
    with pytest.raises(Rejected, match="attachment_conflict"):
        bridge.share(token(runtime), request)
    assert service.store.upload("alice", file_id).data.read_bytes() == request.content.encode()
    assert service.store.history("alice")["turns"][0]["shared_files"] == []


@pytest.mark.parametrize("name,content", [
    ("fake.pdf", "%PDF-pretend"), ("fake.docx", "PKpretend"), ("fake.png", "base64 pretended image"),
    ("fake.wav", "RIFF"), ("fake.zip", "text"), ("bad.txt", "has\x00nul"), ("../secret.txt", "text")])
def test_share_only_accepts_text_files_without_arbitrary_path(sharing, name, content):
    service, runtime, bridge, _ = sharing
    with pytest.raises(Rejected): bridge.share(token(runtime), call(runtime, name=name, content=content))
    assert service.store.library("alice")["files"] == []
    assert not tuple(service.store.files_path.iterdir())


@pytest.mark.parametrize("state", ["completed", "failed", "cancelled", "interrupted", "stopping"])
def test_terminal_runtime_cannot_share(sharing, state):
    service, runtime, bridge, _ = sharing
    list(runtime.runs.values())[-1]["status"] = state
    with pytest.raises(Rejected, match="document_access_denied"):
        bridge.share(token(runtime), call(runtime))
    assert service.store.library("alice")["files"] == []


def test_cancelled_saved_turn_and_expired_grant_cannot_share(sharing):
    service, runtime, bridge, now = sharing
    scope, request = token(runtime), call(runtime)
    turn = service.store.pending("alice")
    now[0] = turn["retry_until"]
    with pytest.raises(Rejected): bridge.share(scope, request)
    now[0] = 1000
    service.store.observe(turn, "cancelled")
    with pytest.raises(Rejected): bridge.share(scope, request)
    assert not service.store.library("alice")["files"]


def test_revocation_during_file_write_is_checked_before_publication(sharing, monkeypatch):
    service, runtime, bridge, _ = sharing
    initial = bridge._authorize
    calls = []
    def revoke_on_second_check(*args):
        calls.append(1)
        if len(calls) == 2:
            service.store.observe(service.store.pending("alice"), "cancelled")
        return initial(*args)
    monkeypatch.setattr(bridge, "_authorize", revoke_on_second_check)
    with pytest.raises(Rejected): bridge.share(token(runtime), call(runtime))
    assert len(calls) == 2 and not service.store.library("alice")["files"]
    assert not tuple(service.store.files_path.iterdir())


@pytest.mark.parametrize("change", ["expiry", "cancel", "tools", "run", "session", "dispatch"])
def test_publication_transaction_rechecks_saved_scope_after_live_corroboration(sharing, change):
    service, runtime, bridge, now = sharing
    request, scope = call(runtime), token(runtime)
    bridge._authorize(scope, request)
    def after_corroboration():
        turn = service.store.pending("alice")
        if change == "expiry":
            now[0] = turn["retry_until"]
            return
        with service.store.connection() as db:
            if change == "cancel":
                db.execute("UPDATE turns SET status='cancelled' WHERE seq=?", (turn["seq"],))
            elif change == "tools":
                db.execute("UPDATE turns SET tool_policy='[]' WHERE seq=?", (turn["seq"],))
            elif change == "session":
                db.execute("UPDATE conversations SET session_id='other' WHERE owner='alice'")
            else:
                column = {"run": "run_id", "dispatch": "dispatch_key"}[change]
                db.execute(f"UPDATE turns SET {column}='other' WHERE seq=?", (turn["seq"],))
    with pytest.raises(Rejected, match="document_access_denied"):
        service.store.share_file(scope, request.run_id, request.session_id, request.dispatch_key,
            request.name, request.content.encode(), clock=lambda: now[0], before_publish=after_corroboration)
    assert not service.store.library("alice")["files"]
    assert not tuple(service.store.files_path.iterdir())


def test_share_http_rejects_unknown_fields_wrong_token_and_large_text_is_not_upload_capped(sharing):
    service, runtime, bridge, _ = sharing
    client = TestClient(create_app(SyntheticAuth(), service, documents=bridge))
    try:
        body = call(runtime, content="UTF-8 text\n" * 4000).model_dump()
        assert client.post("/internal/documents/share", json=body).status_code == 403
        headers = {"Authorization": "Bearer " + token(runtime)}
        assert client.post("/internal/documents/share", json={**body, "path": "/etc/passwd"}, headers=headers).status_code == 422
        assert client.post("/internal/documents/share", json={**body, "content": 12}, headers=headers).status_code == 422
        response = client.post("/internal/documents/share", json=body, headers=headers)
        assert response.status_code == 200
        assert service.store.upload("alice", response.json()["file"]["file_id"]).data.read_bytes() == body["content"].encode()
    finally:
        client.close()


def test_bridge_configured_for_another_owner_cannot_publish(sharing):
    service, runtime, _, now = sharing
    bridge = DocumentBridge(service.store, runtime.client, owner_id="bob", clock=lambda: now[0])
    with pytest.raises(Rejected, match="document_access_denied"):
        bridge.share(token(runtime), call(runtime))
    assert not service.store.library("alice")["files"]


def test_file_metadata_and_assistant_association_rollback_together(sharing, monkeypatch):
    service, runtime, bridge, _ = sharing
    def fail_before_commit(*args):
        raise RuntimeError("synthetic result preparation failure")
    monkeypatch.setattr(service.store, "_shared_file", fail_before_commit)
    with pytest.raises(RuntimeError):
        bridge.share(token(runtime), call(runtime))
    with service.store.connection() as db:
        assert db.execute("SELECT count(*) FROM uploads").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM assistant_files").fetchone()[0] == 0
    assert not service.store.library("alice")["files"]
    # A failed commit may retain an unpublished complete original. Never remove
    # possible committed bytes or advertise an orphan as a shared file.
    assert not any(path.name.startswith("upload-") for path in service.store.files_path.iterdir())


def test_filename_in_prose_does_not_manufacture_a_shared_file(sharing):
    service, runtime, _, _ = sharing
    list(runtime.runs.values())[-1].update(status="completed", output="I created report.pdf for you.")
    history = service.poll("alice")
    assert history["turns"][0]["shared_files"] == []
    assert not service.store.library("alice", source="assistant")["files"]


@pytest.mark.parametrize("field", ["run_id", "session_id", "dispatch_key"])
def test_claimed_run_identity_cannot_share(sharing, field):
    service, runtime, bridge, _ = sharing
    with pytest.raises(Rejected):
        bridge.share(token(runtime), call(runtime).model_copy(update={field: "foreign_identity"}))
    assert service.store.library("alice")["files"] == []


def test_saved_tool_policy_and_live_tools_must_include_file_share(sharing):
    service, runtime, bridge, _ = sharing
    list(runtime.runs.values())[-1]["allowed_tools"] = ["document_search", "document_read"]
    with pytest.raises(Rejected): bridge.share(token(runtime), call(runtime))
    with service.store.connection() as db:
        db.execute("UPDATE turns SET tool_policy=?", (json.dumps(["document_search", "document_read"]),))
    with pytest.raises(Rejected): bridge.share(token(runtime), call(runtime))
    assert service.store.library("alice")["files"] == []


@pytest.mark.parametrize("supported,version", [(False, 1), (True, 2), (True, True)])
def test_old_or_unknown_capability_retains_original_document_tools(tmp_path, supported, version):
    runtime = SharingRuntime()
    runtime.sharing, runtime.sharing_version = supported, version
    store = ChatStore(tmp_path / "chat.sqlite3")
    service = ChatService(store, runtime.client, owner_id="alice", clock=lambda: 1000, document_access=True)
    bridge = DocumentBridge(store, runtime.client, owner_id="alice", clock=lambda: 1000)
    try:
        service.send("alice", str(uuid4()), "Read")
        assert runtime.requests[-1]["allowed_tools"] == ["document_search", "document_read"]
        assert "file_share(name, content)" not in runtime.requests[-1]["input"]
        with pytest.raises(Rejected): bridge.share(token(runtime), call(runtime))
        assert not store.library("alice")["files"]
    finally:
        runtime.client.close()


def test_missing_document_access_never_selects_share_tool(tmp_path):
    runtime = SharingRuntime()
    service = ChatService(ChatStore(tmp_path / "chat.sqlite3"), runtime.client, owner_id="alice", clock=lambda: 1000)
    try:
        service.send("alice", str(uuid4()), "Say hello")
        assert runtime.requests[-1]["disable_tools"] is True
        assert "document_scope_token" not in runtime.requests[-1]
    finally:
        runtime.client.close()


def test_lost_admission_ack_keeps_new_sharing_policy_and_never_downgrades(tmp_path):
    runtime = SharingRuntime()
    store = ChatStore(tmp_path / "chat.sqlite3")
    service = ChatService(store, runtime.client, owner_id="alice", clock=lambda: 1000, document_access=True)
    request_id = str(uuid4())
    runtime.lose_ack = True
    try:
        with pytest.raises(Rejected, match="assistant_unavailable"):
            service.send("alice", request_id, "Make a report")
        runtime.sharing = False
        with pytest.raises(Rejected, match="chat_capability_unavailable"):
            service.retry("alice", request_id)
        assert len(runtime.requests) == 1
        runtime.sharing = True
        service.retry("alice", request_id)
        assert runtime.requests[0] == runtime.requests[1]
    finally:
        runtime.client.close()


def test_native_share_handler_uses_bound_context_and_redacts_failures(monkeypatch):
    from tests.test_hermes_runtime_bridge import bridge as native
    seen = []
    class Callback:
        def post(self, operation, bound, arguments):
            seen.append((operation, bound, arguments))
            return {"kind": "file", "file": {"download_url": "/chat/files/id/content"}}
    monkeypatch.setattr(native, "_callback", Callback())
    marker = native.bind_run_context("run1", "chat1", "dispatch1", "A" * 43)
    try:
        result = json.loads(native.file_share_handler({"name": "report.md", "content": "Literal $() text"}, task_id="chat1"))
        assert result["kind"] == "file"
        assert seen[0][0] == "share" and seen[0][1].run_id == "run1"
        assert seen[0][2] == {"name": "report.md", "content": "Literal $() text"}
        assert json.loads(native.file_share_handler({"name": "report.md", "content": "safe", "path": "/etc/passwd"})) == {"error": "file_share_unavailable"}
        assert json.loads(native.file_share_handler({"name": "report.md", "content": "safe"}, task_id="foreign")) == {"error": "file_share_unavailable"}
        monkeypatch.setattr(native._callback, "post", lambda *args: (_ for _ in ()).throw(ValueError("secret content private token")))
        assert json.loads(native.file_share_handler({"name": "report.md", "content": "safe"})) == {"error": "file_share_unavailable"}
    finally:
        native.reset_run_context(marker)
    assert json.loads(native.file_share_handler({"name": "report.md", "content": "safe"})) == {"error": "file_share_unavailable"}


def test_native_share_registration_capability_and_document_bound_admission(monkeypatch):
    from tests.test_hermes_runtime_bridge import bridge as native
    entries = {}
    tools, registry_module = ModuleType("tools"), ModuleType("tools.registry")
    registry_module.registry = SimpleNamespace(get_entry=entries.get)
    monkeypatch.setitem(sys.modules, "tools", tools)
    monkeypatch.setitem(sys.modules, "tools.registry", registry_module)
    monkeypatch.setattr(native.Callback, "__post_init__", lambda self: None)
    class Plugin:
        def get_config(self, name):
            return {"callback_base_url": "https://127.0.0.1", "callback_ca_file": "fixture", "callback_tls_server_name": "192.168.50.65"}.get(name)
        def register_tool(self, **tool): entries[tool["name"]] = SimpleNamespace(**tool)
    previous = native._callback
    try:
        native.register(Plugin())
        assert set(entries) == {"document_search", "document_read", "file_share"}
        assert entries["file_share"].schema["parameters"]["additionalProperties"] is False
        features = native.features(SimpleNamespace(_run_idempotency_store=SimpleNamespace(durable=True)))
        assert features["runs_file_share"] == {"supported": True, "version": 1}
        body = {"session_id": "chat1", "allowed_tools": ["document_search", "document_read", "file_share"], "document_scope_token": "A" * 43}
        assert native.validate_admission(body, "dispatch1", True) is None
        assert native.validate_admission({"session_id": "chat1", "allowed_tools": ["file_share"]}, "dispatch1", True) == "file_share_scope_required"
        assert native.validate_admission(body, "dispatch1", False) == "document_scope_unavailable"
        entries.pop("file_share")
        assert native.features(SimpleNamespace(_run_idempotency_store=SimpleNamespace(durable=True)))["runs_file_share"]["supported"] is False
    finally:
        native._callback = previous
