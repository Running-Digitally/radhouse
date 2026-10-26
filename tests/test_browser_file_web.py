"""Owner authentication and scoped native callbacks precede file consumption."""
import base64
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from radhouse.chat.app import create_app
from radhouse.chat.document_bridge import FileContentCall
from radhouse.domain.tasks import Rejected
from tests.test_browser_session_web import app, HEADERS, CONTROL
from tests.test_browser_files import original
from tests.test_document_bridge import stack, context, token


def test_browser_file_routes_deny_auth_and_recheck_before_publish(app, monkeypatch):
    client, auth, native, store, browser = app
    client.cookies.clear()
    assert client.post("/chat/browser/files", json=CONTROL, headers=HEADERS).status_code == 401
    assert native.calls == []
    client.cookies.set(auth.cookie_name, "synthetic-cookie")
    client.post("/chat/browser/open", json={}, headers=HEADERS)
    item = original(store)
    effects = []
    def transfer(session, operation, body):
        value = body["file"]; effects.append(value["action"])
        if value["action"] == "write":
            auth.revision += 1
            return {"offset": value["offset"] + len(base64.b64decode(value["data"]))}
        return {"accepted": True}
    monkeypatch.setattr(native, "browser_session", transfer)
    response = client.post("/chat/browser/files/upload", json={**CONTROL, "file_id": item.file_id,
        "chooser": "a" * 32, "destination": "https://example.org/upload"}, headers=HEADERS)
    assert response.status_code == 409 and effects == ["begin", "write"]


def test_private_device_upload_and_explicit_share_are_owner_authenticated(app):
    client, auth, native, store, browser = app
    identity = str(uuid4())
    response = client.put("/chat/files/" + identity + "?name=private.txt&private=true",
        content=b"synthetic private file", headers=HEADERS)
    assert response.status_code == 200
    assert store.library("alice")["files"][0]["private"] is True
    client.cookies.clear()
    assert client.post("/chat/files/" + identity + "/share", json={}, headers=HEADERS).status_code == 401
    client.cookies.set(auth.cookie_name, "synthetic-cookie")
    assert client.post("/chat/files/" + identity + "/share", json={}, headers=HEADERS).json()["private"] is False


def test_content_callback_needs_browser_upload_grant_and_rejects_private_file(stack):
    service, runtime, bridge, _ = stack
    public = original(service.store, private=False, data=b"authorized original" * 3000)
    private = original(service.store, private=True)
    service.send("alice", "file-transfer-turn", "Upload the selected original", ())
    call = FileContentCall(**context(runtime).model_dump(exclude_none=True), file_id=public.file_id, offset=0)
    with pytest.raises(Rejected):
        bridge.content(token(runtime), call)
    with service.store.connection() as db:
        db.execute("UPDATE turns SET tool_policy=? WHERE request_id='file-transfer-turn'",
            ('["document_search","document_read","browser_upload"]',))
    run = list(runtime.runs.values())[-1]
    run["allowed_tools"] = ["document_search", "document_read", "browser_upload"]
    assert set(service.store.document_grant(token(runtime), 1000)["allowed_tools"]) == set(run["allowed_tools"])
    value = bridge.content(token(runtime), call)
    assert len(base64.b64decode(value["data"])) == 32768
    assert value["sha256"] == public.sha256
    with pytest.raises(Rejected):
        bridge.content(token(runtime), call.model_copy(update={"file_id": private.file_id}))
    with pytest.raises(Rejected):
        bridge.content(token(runtime), call.model_copy(update={"offset": public.size + 1}))
    run["status"] = "completed"
    with pytest.raises(Rejected):
        bridge.content(token(runtime), call)
