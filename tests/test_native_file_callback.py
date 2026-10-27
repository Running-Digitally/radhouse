"""Exercise native callback parsing against real web-authorized file chunks."""
import asyncio
import base64
from contextlib import contextmanager
import hashlib
from io import BytesIO
import json
from types import SimpleNamespace

import pytest

from radhouse.chat.document_bridge import FileContentCall
from tests.test_browser_files import guest, original
from tests.test_document_bridge import stack, context, token
from tests.test_hermes_runtime_bridge import bridge
from tests.test_native_browser_files import native
from tests.test_selkies_control import control, fixture


def callback(tmp_path, monkeypatch, respond):
    ca = tmp_path / "synthetic-ca"
    ca.write_text("transport is replaced in this test")
    monkeypatch.setattr(bridge.ssl, "create_default_context", lambda **_: object())

    def open_request(request, timeout):
        assert timeout == 20
        assert request.full_url.startswith("https://127.0.0.1:8443/internal/documents/")
        return BytesIO(json.dumps(respond(request)).encode())

    monkeypatch.setattr(bridge, "build_opener", lambda *_: SimpleNamespace(open=open_request))
    return bridge.Callback("https://127.0.0.1:8443", str(ca), "localhost")


@pytest.mark.parametrize("private", [False, True])
def test_real_callback_carries_web_granted_chunks_to_agent_upload(stack, tmp_path, monkeypatch, private):
    service, runtime, web, _ = stack
    data = b"authorized synthetic original" * 3000
    item = original(service.store, private=private, data=data)
    service.send("alice", "callback-upload", "Upload this original", ())
    tools = ["document_read", "document_search", "browser_upload"]
    with service.store.connection() as db:
        db.execute("UPDATE turns SET tool_policy=? WHERE request_id='callback-upload'", (json.dumps(tools),))
    list(runtime.runs.values())[-1]["allowed_tools"] = tools
    document_context = context(runtime)
    calls = []

    def respond(request):
        assert request.headers["Authorization"] == "Bearer " + token(runtime)
        body = json.loads(request.data)
        calls.append(body["offset"])
        return web.content(token(runtime), FileContentCall(**body))

    actual_callback = callback(tmp_path, monkeypatch, respond)

    async def scenario():
        f = fixture(tmp_path)
        run_context = bridge.DocumentRunContext(document_context.run_id, document_context.session_id,
            document_context.dispatch_key, token(runtime))
        identity = control.BrowserIdentity("callback-conversation", document_context.session_id, "callback-generation")
        f.c.bind_browser(identity, control.RunBinding(document_context.run_id,
            document_context.session_id, document_context.dispatch_key), "alice")
        effects, chunks = [], []

        async def call(operation, **value):
            effects.append(value["action"])
            if value["action"] == "list":
                return {"chooser": {"id": "b" * 32, "destination": "https://example.org/upload"}}
            if value["action"] == "write":
                chunks.append(base64.b64decode(value["data"], validate=True))
            return {"applied": True}

        @contextmanager
        def browser_operation(_):
            yield SimpleNamespace(identity=identity)

        native_bridge = SimpleNamespace(_callback=actual_callback, _controller=f.c,
            _streaming=SimpleNamespace(runtime=SimpleNamespace(loop=asyncio.get_running_loop(),
                remote=SimpleNamespace(call=call), boundary=f.boundary)),
            current_run_context=lambda **_: run_context, agent_browser_operation=browser_operation)
        monkeypatch.setattr(native, "file_module", lambda _: guest)
        result = json.loads(await asyncio.to_thread(native.agent_upload, native_bridge,
            {"file_id": item.file_id, "destination": "https://example.org/upload"}))
        if private:
            assert result == {"error": "browser_file_transfer_unavailable"}
            assert effects == ["list"]
        else:
            assert result == {"applied": True}
            assert effects == ["list", "begin", "write", "write", "write", "commit"]
            assert calls == [0, 32768, 65536]
            assert b"".join(chunks) == data

    asyncio.run(scenario())


@pytest.mark.parametrize("change", [
    {"file_id": "other"}, {"offset": 1}, {"offset": False}, {"size": True},
    {"size": -1}, {"size": 2**53}, {"data": "!"}, {"data": ""},
    {"data": base64.b64encode(b"x" * 32769).decode()}, {"sha256": "bad"},
    {"name": "../escape"}, {"name": ""}, {"kind": "catalog"},
])
def test_content_callback_rejects_wrong_identity_shape_or_bounds(tmp_path, monkeypatch, change):
    value = {"file_id": "granted", "offset": 0, "size": 3, "name": "fixture.txt",
        "sha256": hashlib.sha256(b"abc").hexdigest(), "data": "YWJj"}
    client = callback(tmp_path, monkeypatch, lambda _: {**value, **change})
    with pytest.raises(ValueError):
        client.post("content", bridge.DocumentRunContext("run", "session", "dispatch", "scope"),
            {"file_id": "granted", "offset": 0})


@pytest.mark.parametrize("operation,body", [
    ("read", {"kind": "catalog"}), ("read", {"kind": "passages"}),
    ("share", {"kind": "file"}),
    ("content", {"file_id": "empty", "offset": 0, "size": 0, "name": "empty.txt",
        "sha256": hashlib.sha256(b"").hexdigest(), "data": ""}),
])
def test_callback_preserves_supported_responses_including_empty_file(tmp_path, monkeypatch, operation, body):
    client = callback(tmp_path, monkeypatch, lambda _: body)
    assert client.post(operation, bridge.DocumentRunContext("run", "session", "dispatch", "scope"),
        {"file_id": "empty", "offset": 0}) == body
