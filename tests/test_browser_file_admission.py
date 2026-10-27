"""The live document/browser feature combination uses frozen tool authority."""
import hashlib
from uuid import uuid4

import httpx
import pytest

from radhouse.chat.service import ChatService
from radhouse.chat.store import ChatStore
from radhouse.domain.tasks import Rejected
from tests.test_document_bridge import Runtime, complete


OWNER = {"principal_id": "alice", "conversation_id": "personal-alice:alice:radhouse"}
BINDING = {"browser_owner": OWNER}


class FileRuntime(Runtime):
    browser_files = True

    def respond(self, request):
        response = super().respond(request)
        if request.url.path != "/v1/capabilities":
            return response
        value = response.json()
        value["features"].update({
            "runs_browser_view": {"supported": True, "version": 1, "mode": "same_session_view_only"},
            "runs_browser_control": {"supported": True, "version": 1, "mode": "owner_session"},
            "runs_browser_files": {"supported": self.browser_files, "version": 1},
        })
        return httpx.Response(200, json=value)


@pytest.fixture
def stack(tmp_path):
    runtime = FileRuntime()
    service = ChatService(ChatStore(tmp_path / "chat.sqlite3"), runtime.client,
        owner_id="alice", clock=lambda: 1000, document_access=True,
        browser_enabled=True, browser_control=True)
    yield service, runtime
    runtime.client.close()


@pytest.mark.parametrize("disabled", [None, "documents", "browser", "control", "capability", "owner"])
def test_upload_tool_requires_all_live_admission_conditions(stack, disabled):
    service, runtime = stack
    service.document_access = disabled != "documents"
    service.browser_enabled = disabled != "browser"
    service.browser_control = disabled != "control"
    runtime.browser_files = disabled != "capability"
    request_id = str(uuid4())
    result = service.send("alice", request_id, "Use the authorized synthetic file",
        browser_data={} if disabled in {"owner", "browser"} else BINDING)
    assert result["accepted_request_id"] == request_id
    assert len(runtime.requests) == 1
    body = runtime.requests[0]
    assert ("browser_upload" in body["allowed_tools"]) is (disabled is None)
    assert ("document_scope_token" in body) is (disabled != "documents")
    saved = service.store.find("alice", request_id)
    assert tuple(body["allowed_tools"]) == service.store.tools(saved)
    assert saved["run_id"] is not None


def test_retry_cannot_add_newly_available_upload_tool(stack):
    service, runtime = stack
    runtime.browser_files = False
    runtime.lose_ack = True
    request_id = str(uuid4())
    with pytest.raises(Rejected, match="assistant_unavailable"):
        service.send("alice", request_id, "Synthetic retry", browser_data=BINDING)
    original = runtime.requests[0]
    runtime.browser_files = True
    service.retry("alice", request_id)
    assert runtime.requests == [original, original]
    assert "browser_upload" not in original["allowed_tools"]


def test_retry_refuses_removed_upload_capability(stack):
    service, runtime = stack
    runtime.lose_ack = True
    request_id = str(uuid4())
    with pytest.raises(Rejected, match="assistant_unavailable"):
        service.send("alice", request_id, "Synthetic retry", browser_data=BINDING)
    assert "browser_upload" in runtime.requests[0]["allowed_tools"]
    runtime.browser_files = False
    with pytest.raises(Rejected, match="chat_capability_unavailable"):
        service.retry("alice", request_id)
    assert len(runtime.requests) == 1


def test_live_feature_combination_keeps_private_files_out_of_frozen_grants(stack):
    service, runtime = stack
    identity = str(uuid4())
    data = b"Synthetic private original"
    stream, path = service.store.begin_upload("alice", identity, "synthetic.txt")
    with stream:
        stream.write(data)
    service.store.commit_upload("alice", identity, "synthetic.txt", path, "text/plain", "text",
        hashlib.sha256(data).hexdigest(), len(data),
        browser={"private": True, "producer": "user", "origin": "browser", "created_at": 1000})
    service.send("alice", str(uuid4()), "List authorized files", browser_data=BINDING)
    first_token = runtime.requests[0]["document_scope_token"]
    service.store.share_browser_file("alice", identity)
    complete(service, runtime)
    service.send("alice", str(uuid4()), "Use the shared file", browser_data=BINDING)
    second_token = runtime.requests[1]["document_scope_token"]
    with service.store.connection() as db:
        old = db.execute("SELECT file_id FROM document_grant_files WHERE token=?", (first_token,)).fetchall()
        new = db.execute("SELECT file_id FROM document_grant_files WHERE token=?", (second_token,)).fetchall()
    assert old == []
    assert [row["file_id"] for row in new] == [identity]
    assert all("browser_upload" in request["allowed_tools"] for request in runtime.requests)
