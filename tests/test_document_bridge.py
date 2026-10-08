"""Saved-turn capability tests through the real web/client/parser boundary."""
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from threading import Event
from uuid import uuid4

import httpx
import pytest

from radhouse.chat.app import create_app
from radhouse.chat.document_bridge import DocumentBridge, DocumentCall
from radhouse.chat.service import ChatService
from radhouse.chat.store import ChatStore
from radhouse.domain.tasks import Rejected
from radhouse.integrations.hermes import HermesRunsClient
from tests.test_minimal_chat import SyntheticAuth


TOOLS = ("document_search", "document_read")


class Runtime:
    def __init__(self):
        self.requests, self.runs, self.probes = [], {}, []
        self.before_ack = None
        self.lose_ack = False
        self.doc_capability = True
        self.client = HermesRunsClient("http://127.0.0.1", "fixture-private", transport=httpx.MockTransport(self.respond))

    def respond(self, request):
        if request.url.path == "/v1/capabilities":
            return httpx.Response(200, json={"features": {
                "runs_idempotency": {"supported": True, "durable": True, "retention_seconds": 3600},
                "runs_disable_tools": {"supported": True},
                "runs_allowed_tools": {"supported": True, "durable": True, "version": 1,
                    "mode": "exact_subset_of_profile", "max_names": 32},
                "runs_document_scope": {"supported": self.doc_capability, "durable": True,
                    "version": 1, "scope": "saved_turn_files"}}})
        if request.method == "POST":
            body = json.loads(request.content)
            self.requests.append(body)
            key = request.headers["Idempotency-Key"]
            replay = key in self.runs
            run = self.runs.setdefault(key, {"run_id": "run_" + uuid4().hex,
                "session_id": body["session_id"], "dispatch_key": key,
                "allowed_tools": body.get("allowed_tools", []), "status": "running", "output": None})
            if self.before_ack:
                self.before_ack(body, run)
            if self.lose_ack:
                self.lose_ack = False
                raise httpx.ReadError("fixture lost ack", request=request)
            return httpx.Response(202, headers={"Idempotency-Replayed": str(replay).lower()},
                json={"run_id": run["run_id"], "status": "running" if replay else "started", "replayed": replay})
        run_id = request.url.path.split("/")[-1]
        self.probes.append(run_id)
        run = next((r for r in self.runs.values() if r["run_id"] == run_id), None)
        return httpx.Response(200, json=run) if run else httpx.Response(404)


@pytest.fixture
def stack(tmp_path):
    runtime = Runtime()
    store = ChatStore(tmp_path / "chat.sqlite3")
    now = [1000]
    service = ChatService(store, runtime.client, owner_id="alice", clock=lambda: now[0], document_access=True)
    bridge = DocumentBridge(store, runtime.client, owner_id="alice", clock=lambda: now[0])
    yield service, runtime, bridge, now
    runtime.client.close()


def original(store, data=b"A durable original.\n", *, owner="alice", name="plan.txt"):
    file_id = str(uuid4())
    stream, path = store.begin_upload(owner, file_id, name)
    with stream:
        stream.write(data)
    return store.commit_upload(owner, file_id, name, path, "text/plain", "text", hashlib.sha256(data).hexdigest(), len(data))


def context(runtime, **fields):
    run = list(runtime.runs.values())[-1]
    return DocumentCall(run_id=run["run_id"], session_id=run["session_id"], dispatch_key=run["dispatch_key"], **fields)


def token(runtime):
    return runtime.requests[-1]["document_scope_token"]


def complete(service, runtime):
    run = list(runtime.runs.values())[-1]
    run.update(status="completed", output="A cited answer.")
    service.poll("alice")


@pytest.mark.parametrize("operation", ["read", "search"])
def test_changed_original_denied_even_when_upload_and_grant_digests_agree(stack, operation):
    service, runtime, bridge, _ = stack
    attachment = original(service.store, b"Expected answer: 100.\n")
    service.send("alice", "Read the answer", "changed-original", (attachment,))
    attachment.data.write_bytes(b"Replaced answer: 900.\n")
    scope = bridge.grant(token(runtime))
    assert service.store.upload("alice", attachment.file_id).sha256 == scope["files"][attachment.file_id]
    call = context(runtime, file_id=attachment.file_id, **({"query": "answer"} if operation == "search" else {}))
    prepared_argument_1 = token(runtime)
    with pytest.raises(Rejected, match="document_source_changed") as denial:
        bridge.execute(prepared_argument_1, call, operation)
    assert denial.value.status == 409


def test_catalog_is_upload_metadata_without_reading_or_claiming_current_bytes(stack, monkeypatch):
    service, runtime, bridge, _ = stack
    attachment = original(service.store, b"Expected original.\n")
    service.send("alice", "Inspect the files", "catalog-receipt", (attachment,))
    attachment.data.write_bytes(b"Changed on disk.\n")
    import os
    import subprocess
    monkeypatch.setattr(os, "open", lambda *a, **kw: pytest.fail("catalog opened original"))
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: pytest.fail("catalog launched parser"))
    result = bridge.execute(token(runtime), context(runtime), "read")
    assert result["files"][0]["sha256"] == attachment.sha256
    assert result["files"][0]["sha256_basis"] == "upload_receipt"


def test_large_original_is_read_on_demand_before_dispatch_acknowledgment(stack):
    service, runtime, bridge, _ = stack
    text = b"Ordinary text.\n" * 20000 + b"Final total is 73129.\n"
    attachment = original(service.store, text)
    received = []

    def first_tool(body, run):
        with ThreadPoolExecutor(max_workers=1) as pool:
            cursor = None
            while True:
                result = pool.submit(bridge.execute, body["document_scope_token"],
                    context(runtime, file_id=attachment.file_id, locator="text:line:20001", cursor=cursor), "read").result(timeout=5)
                if result["passages"] or not result["next_cursor"]:
                    break
                cursor = result["next_cursor"]
        received.append(result)

    runtime.before_ack = first_tool
    history = service.send("alice", str(uuid4()), "What is the final total?", (attachment,))
    assert received[0]["kind"] == "passages"
    assert received[0]["passages"][0]["text"] == "Final total is 73129.\n"
    assert "73129" not in runtime.requests[0]["input"]
    assert "Ordinary text" not in runtime.requests[0]["input"]
    assert runtime.requests[0]["allowed_tools"] == list(TOOLS)
    assert runtime.requests[0].get("disable_tools", False) is False
    assert history["turns"][0]["attachments"][0]["reading_state"] == "available"
    assert "document_scope_token" not in json.dumps(history)
    assert attachment.data.read_bytes() == text


def test_first_tool_recovers_lost_ack_without_resubmitting(stack):
    service, runtime, bridge, _ = stack
    attachment = original(service.store)
    runtime.before_ack = lambda body, run: bridge.execute(body["document_scope_token"], context(runtime), "read")
    runtime.lose_ack = True
    key = str(uuid4())
    with pytest.raises(Rejected, match="assistant_unavailable"):
        service.send("alice", key, "Read it", (attachment,))
    reopened = ChatService(ChatStore(service.store.path), runtime.client, owner_id="alice", clock=lambda: 1001, document_access=True)
    assert reopened.retry("alice", key)["accepted_request_id"] == key
    assert len(runtime.requests) == 1
    assert reopened.store.pending("alice")["run_id"] == context(runtime).run_id


def test_lost_ack_reuses_saved_grant_and_hmac_cursors_after_restart(stack):
    service, runtime, bridge, _ = stack
    attachment = original(service.store, b"Long line: " + b"x" * 100000 + b"\n")
    runtime.lose_ack = True
    key = str(uuid4())
    with pytest.raises(Rejected): service.send("alice", key, "Read", (attachment,))
    first_token = token(runtime)
    service = ChatService(ChatStore(service.store.path), runtime.client, owner_id="alice", clock=lambda: 1001, document_access=True)
    service.retry("alice", key)
    assert token(runtime) == first_token
    assert runtime.requests[0] == runtime.requests[1]
    first = bridge.execute(first_token, context(runtime, file_id=attachment.file_id), "read")
    assert first['next_cursor']
    assert not first['complete']
    reopened = DocumentBridge(ChatStore(service.store.path), runtime.client, owner_id="alice", clock=lambda: 1002)
    second = reopened.execute(first_token, context(runtime, file_id=attachment.file_id, cursor=first["next_cursor"]), "read")
    assert second['passages']
    assert second != first


def test_catalog_contains_prior_attachments_but_not_unattached_foreign_or_future_files(stack):
    service, runtime, bridge, _ = stack
    prior = original(service.store, name="prior.txt")
    service.send("alice", str(uuid4()), "First", (prior,))
    complete(service, runtime)
    unattached = original(service.store, name="unattached.txt")
    foreign = original(service.store, owner="bob", name="foreign.txt")
    current = original(service.store, name="current.txt")
    service.send("alice", str(uuid4()), "Continue", (current,))
    grant_token, call = token(runtime), context(runtime)
    future = original(service.store, name="future.txt")
    catalog = bridge.execute(grant_token, call, "read")
    assert {f["file_id"] for f in catalog["files"]} == {prior.file_id, current.file_id}
    assert 'storage_name' not in json.dumps(catalog)
    assert str(service.store.files_path) not in json.dumps(catalog)
    for attachment in (unattached, foreign, future):
        prepared_argument_2 = context(runtime, file_id=attachment.file_id)
        with pytest.raises(Rejected, match="attachment_not_found"):
            bridge.execute(grant_token, prepared_argument_2, 'read')
    # Even a later saved attachment cannot grow an older turn's immutable scope.
    complete(service, runtime)
    service.send("alice", str(uuid4()), "Third", (future,))
    with pytest.raises(Rejected, match="document_access_denied"):
        bridge.execute(grant_token, call, "read")


def test_catalog_pages_are_bounded_and_signed(stack):
    service, runtime, bridge, _ = stack
    files = tuple(original(service.store, name=f"file{i}.txt") for i in range(21))
    service.send("alice", str(uuid4()), "List", files)
    first = bridge.execute(token(runtime), context(runtime), "read")
    assert len(first['files']) == 16
    assert first['next_cursor']
    assert not first['complete']
    second = bridge.execute(token(runtime), context(runtime, cursor=first["next_cursor"]), "read")
    assert len(second['files']) == 5
    assert second['complete']
    assert len({f["file_id"] for f in first["files"] + second["files"]}) == 21
    altered = json.loads(base64.urlsafe_b64decode(first["next_cursor"]))
    altered["body"]["offset"] = 0
    cursor = base64.urlsafe_b64encode(json.dumps(altered).encode()).decode()
    prepared_argument_1_2 = token(runtime)
    prepared_argument_2_2 = context(runtime, cursor=cursor)
    with pytest.raises(Rejected, match="document_cursor_invalid"):
        bridge.execute(prepared_argument_1_2, prepared_argument_2_2, 'read')


@pytest.mark.parametrize("field,value", [("session_id", "different"), ("dispatch_key", "different"), ("run_id", "different")])
def test_model_claimed_context_cannot_replace_saved_context(stack, field, value):
    service, runtime, bridge, _ = stack
    service.send("alice", str(uuid4()), "Read")
    call = context(runtime).model_copy(update={field: value})
    prepared_argument_1_3 = token(runtime)
    with pytest.raises(Rejected, match="document_access_denied"):
        bridge.execute(prepared_argument_1_3, call, 'read')
    assert runtime.probes == []


@pytest.mark.parametrize("field,value", [("session_id", "other"), ("dispatch_key", "other"),
    ("allowed_tools", ["document_read", "document_search", "terminal"]), ("status", "completed")])
def test_callback_requires_live_exact_runtime_context(stack, field, value):
    service, runtime, bridge, _ = stack
    service.send("alice", str(uuid4()), "Read")
    call = context(runtime)
    list(runtime.runs.values())[-1][field] = value
    prepared_argument_1_4 = token(runtime)
    with pytest.raises(Rejected, match="document_access_denied"):
        bridge.execute(prepared_argument_1_4, call, 'read')


@pytest.mark.parametrize("invalidate", ["terminal", "expired"])
def test_terminal_and_expired_grants_deny_before_network(stack, invalidate):
    service, runtime, bridge, now = stack
    service.send("alice", str(uuid4()), "Read")
    grant_token, call = token(runtime), context(runtime)
    if invalidate == "terminal": complete(service, runtime)
    else: now[0] = 4540
    runtime.probes.clear()
    with pytest.raises(Rejected, match="document_access_denied"):
        bridge.execute(grant_token, call, "read")
    assert runtime.probes == []


def test_cancel_during_read_discards_passages(stack, monkeypatch):
    service, runtime, bridge, _ = stack
    service.send("alice", str(uuid4()), "Read", (original(service.store),))
    original_catalog = bridge._catalog
    def cancelled(*args):
        result = original_catalog(*args)
        service.store.observe(service.store.pending("alice"), "cancelled")
        return result
    monkeypatch.setattr(bridge, "_catalog", cancelled)
    prepared_argument_1_5 = token(runtime)
    prepared_argument_2_3 = context(runtime)
    with pytest.raises(Rejected, match="document_access_denied"):
        bridge.execute(prepared_argument_1_5, prepared_argument_2_3, 'read')


def test_no_automatic_tool_upgrade_for_an_uncertain_legacy_turn(stack):
    service, runtime, _, _ = stack
    legacy = ChatService(service.store, runtime.client, owner_id="alice", clock=lambda: 1000)
    runtime.lose_ack = True
    key = str(uuid4())
    with pytest.raises(Rejected): legacy.send("alice", key, "Legacy")
    service.retry("alice", key)
    assert all(r["disable_tools"] is True and "document_scope_token" not in r for r in runtime.requests)
    assert runtime.requests[0] == runtime.requests[1]


def test_missing_runtime_document_capability_refuses_before_reservation(stack):
    service, runtime, _, _ = stack
    runtime.doc_capability = False
    with pytest.raises(Rejected, match="document_capability_unavailable"):
        service.send("alice", str(uuid4()), "Read")
    assert not runtime.requests
    assert service.store.history('alice')['turns'] == []


def test_concurrent_retries_share_dispatch_without_holding_callback_lock(stack):
    service, runtime, bridge, _ = stack
    entered, release = Event(), Event()
    def callback(body, run):
        bridge.execute(body["document_scope_token"], context(runtime), "read")
        entered.set()
        assert release.wait(2)
    runtime.before_ack = callback
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(service.send, "alice", key, "Read")
        assert entered.wait(2)
        second = pool.submit(service.send, "alice", key, "Read")
        release.set()
        assert first.result(timeout=3) == second.result(timeout=3)
    assert len(runtime.requests) == 1


def test_http_callback_uses_grant_before_body_and_rejects_extra_identity(stack):
    service, runtime, bridge, _ = stack
    service.send("alice", str(uuid4()), "Read", (original(service.store),))
    # ASGITransport doesn't enter lifespan: runtime observation cannot alter this proof.
    import asyncio
    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(SyntheticAuth(), service, documents=bridge)), base_url="http://127.0.0.1") as client:
            path = "/internal/documents/read"
            assert (await client.post(path, content=b"bad json")).status_code == 403
            assert runtime.probes == []
            headers = {"Authorization": "Bearer " + token(runtime)}
            body = context(runtime).model_dump(exclude_none=True)
            denied = await client.post(path, json={**body, "owner": "alice"}, headers=headers)
            assert denied.status_code == 422
            assert 'alice' not in denied.text
            assert runtime.probes == []
            response = await client.post(path, json=body, headers=headers)
            assert response.status_code == 200
            assert response.json()['kind'] == 'catalog'
            assert response.headers["cache-control"] == "no-store"
            assert token(runtime) not in response.text
            assert (await client.post(path, content=b"x" * 17000, headers=headers)).status_code == 422
    asyncio.run(check())
