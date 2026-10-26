"""Synthetic originals exercise durable intake and the closed guest protocol."""
import asyncio
import base64
import hashlib
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from radhouse.chat.browser_files import BrowserFiles
from radhouse.chat.store import ChatStore
from radhouse.domain.tasks import Rejected

spec = importlib.util.spec_from_file_location("guest_browser_files_test", Path(__file__).parents[1] / "runtime/selkies/browser_files.py")
guest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guest)


def original(store, *, owner="alice", private=True, data=b"synthetic file", name="private.txt"):
    identity = str(uuid4())
    stream, path = store.begin_upload(owner, identity, name)
    with stream:
        stream.write(data); stream.flush(); os.fsync(stream.fileno())
    return store.commit_upload(owner, identity, name, path, "text/plain", "text", hashlib.sha256(data).hexdigest(), len(data),
        browser={"private": private, "producer": "user", "origin": "browser", "created_at": 1000})


def turn(store, request):
    from tests.test_chat_library import saved_turn
    value = saved_turn(store, request, (), now=1001)
    with store.connection() as db:
        db.execute("UPDATE turns SET status='running',retry_until=2000,tool_policy=? WHERE request_id=?", ('["document_read","document_search"]', request))
        row = dict(db.execute("SELECT * FROM turns WHERE request_id=?", (request,)).fetchone())
    return row


def test_private_file_is_owner_visible_and_requires_share_for_future_grant(tmp_path):
    store = ChatStore(tmp_path / "chat.db")
    item = original(store)
    assert store.library("alice")["files"][0]["private"] is True
    assert store.library("bob")["files"] == []
    with pytest.raises(Rejected):
        store.assistant_upload("alice", item.file_id)
    with pytest.raises(Rejected):
        store.share_browser_file("bob", item.file_id)
    first = store.document_grant_for_turn(turn(store, "before-share"))
    assert item.file_id not in store.document_grant(first, 1002)["files"]
    store.share_browser_file("alice", item.file_id)
    assert store.assistant_upload("alice", item.file_id).sha256 == item.sha256
    assert item.file_id not in store.document_grant(first, 1002)["files"]  # Frozen grants cannot grow.
    second = store.document_grant_for_turn(turn(store, "after-share"))
    assert store.document_grant(second, 1002)["files"][item.file_id] == item.sha256


class DownloadRelay:
    def __init__(self, data):
        self.data = data; self.acked = False; self.fail_ack = False; self.bad_chunk = False; self.offsets = []
        self.item = {"id": "b" * 32, "name": "example.bin", "private": 1, "producer": "user",
            "state": "completed", "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}

    def browser_session(self, session, operation, body):
        assert body["collector"] == "alice" and operation == "files"
        value = body["file"]
        if body["launch_id"] is None:
            return {"launches": [{"launch_id": "a" * 32, "generation": "generation"}]}
        if value["action"] == "list":
            return {"downloads": [] if self.acked else [self.item]}
        if value["action"] == "ack":
            if self.fail_ack:
                self.fail_ack = False
                raise OSError("synthetic lost ack")
            assert value["sha256"] == self.item["sha256"]
            self.acked = True; return {"saved": True}
        offset = value["offset"]; self.offsets.append(offset)
        data = self.data[offset:offset + 32768]
        if self.bad_chunk:
            data = b"x" * len(data)
        return {"offset": offset, "size": len(self.data), "sha256": self.item["sha256"], "data": base64.b64encode(data).decode()}


def collector(tmp_path, data):
    store = ChatStore(tmp_path / "chat.db")
    store.browser_session("alice", create=True)
    relay = DownloadRelay(data)
    browser = SimpleNamespace(store=store, owner_id="alice", hermes=relay, clock=lambda: 1000)
    return BrowserFiles(browser), relay


def test_intake_streams_original_and_reconciles_commit_before_lost_ack(tmp_path):
    data = bytes(range(256)) * 1025
    files, relay = collector(tmp_path, data)
    relay.fail_ack = True
    with pytest.raises(OSError):
        files.collect()
    page = files.store.library("alice")["files"]
    assert len(page) == 1 and page[0]["private"] is True
    assert files.store.upload("alice", page[0]["file_id"]).data.read_bytes() == data
    # Recreate the web-side collector, as after a web process restart.
    BrowserFiles(files.browser).collect()
    assert relay.acked and len(files.store.library("alice")["files"]) == 1
    assert max(relay.offsets) > 32768


def test_digest_failure_never_publishes_or_acknowledges(tmp_path):
    files, relay = collector(tmp_path, b"original" * 10000)
    relay.bad_chunk = True
    with pytest.raises(Rejected, match="browser_download_digest_mismatch"):
        files.collect()
    assert not relay.acked and not files.store.library("alice")["files"]
    assert not list(files.store.files_path.iterdir())


@pytest.mark.parametrize("revoke", [False, True])
def test_library_upload_streams_only_selected_original_and_rechecks_session(tmp_path, revoke):
    store = ChatStore(tmp_path / "chat.db")
    data = b"selected bytes" * 5000
    item = original(store, data=data)
    calls = []
    def call(session, tab, operation, body):
        value = body["file"]; calls.append(value)
        if value["action"] == "write":
            return {"offset": value["offset"] + len(base64.b64decode(value["data"]))}
        return {"accepted": True, "applied": True}
    browser = SimpleNamespace(store=store, owner_id="alice", _call=call)
    files = BrowserFiles(browser)
    def check():
        if revoke and any(value["action"] == "write" for value in calls):
            raise Rejected("authentication_required", 401)
    if revoke:
        with pytest.raises(Rejected):
            files.upload("session", "tab", {}, item.file_id, "a" * 32, "https://example.org/upload", check)
        assert all(value["action"] != "commit" for value in calls)
    else:
        assert files.upload("session", "tab", {}, item.file_id, "a" * 32, "https://example.org/upload", check)["applied"]
        assert b"".join(base64.b64decode(value["data"]) for value in calls if value["action"] == "write") == data
        assert calls[-1]["action"] == "commit" and max(len(value.get("data", "")) for value in calls) < 44000
    stranger = original(store, owner="other")
    before = len(calls)
    with pytest.raises(Rejected):
        files.upload("session", "tab", {}, stranger.file_id, "a" * 32, "https://example.org/upload", check)
    assert len(calls) == before


def test_only_the_admitted_runs_nonprivate_download_enters_its_existing_grant(tmp_path):
    store = ChatStore(tmp_path / "chat.db")
    saved = turn(store, "active-download")
    token = store.document_grant_for_turn(saved)
    with store.connection() as db:
        db.execute("UPDATE turns SET run_id='run-1' WHERE seq=?", (saved["seq"],))
        db.execute("UPDATE document_grants SET bound_run_id='run-1' WHERE token=?", (token,))
    for private in (True, False):
        identity = str(uuid4()); data = b"downloaded original"
        stream, path = store.begin_upload("alice", identity, "download.txt")
        with stream: stream.write(data)
        store.commit_upload("alice", identity, "download.txt", path, "text/plain", "text", hashlib.sha256(data).hexdigest(), len(data),
            browser={"private": private, "producer": "assistant", "origin": "browser", "created_at": 1000, "run_id": "run-1"})
        assert (identity in store.document_grant(token, 1002)["files"]) is (not private)
    assert len(store.history("alice")["turns"][0]["shared_files"]) == 1


@pytest.mark.parametrize("value", [
    {"action": "exec", "command": "id"}, {"action": "read", "id": "../secret", "offset": 0},
    {"action": "read", "id": "a" * 32, "offset": -1},
    {"action": "write", "id": "a" * 32, "offset": 0, "data": "!"},
    {"action": "write", "id": "a" * 32, "offset": 0, "data": base64.b64encode(b"x" * 32769).decode()},
    {"action": "list", "path": "/etc/passwd"},
])
def test_file_protocol_rejects_non_capability_input(value):
    with pytest.raises(ValueError):
        guest.validate(value)


def test_guest_upload_refuses_navigation_and_changed_chunks(tmp_path):
    async def scenario():
        files = guest.Files(tmp_path / "files", "a" * 32)
        chooser = {"id": "b" * 32, "destination": "https://example.org/upload", "multiple": False}
        async def state(): return chooser
        files.chooser_state = state
        data = b"example"
        begin = {"action": "begin", "id": "c" * 32, "chooser": "b" * 32,
            "destination": chooser["destination"], "name": "file.txt", "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        await files.execute(begin)
        chunk = {"action": "write", "id": "c" * 32, "offset": 0, "data": base64.b64encode(data).decode()}
        assert await files.execute(chunk) == {"offset": len(data)}
        assert await files.execute(chunk) == {"offset": len(data)}
        with pytest.raises(ValueError, match="upload_conflict"):
            await files.execute({**chunk, "data": base64.b64encode(b"changed").decode()})
        chooser["destination"] = "https://elsewhere.example/"
        with pytest.raises(ValueError, match="file_chooser_changed"):
            await files.execute({"action": "commit", "id": "c" * 32})
        await files.close()
    asyncio.run(scenario())


def test_guest_download_outbox_survives_close_and_refuses_symlinks(tmp_path):
    async def scenario():
        root = tmp_path / "files"
        files = guest.Files(root, "a" * 32)
        guid = str(uuid4()); data = b"synthetic download"
        await files.event({"method": "Browser.downloadWillBegin", "params": {"guid": guid, "suggestedFilename": "../../secret"}})
        path = files.downloads / guid
        path.write_bytes(data)
        await files.event({"method": "Browser.downloadProgress", "params": {"guid": guid, "state": "completed"}})
        await files.close()
        files = guest.Files(root, "a" * 32)
        listing = await files.execute({"action": "list"})
        item = listing["downloads"][0]
        assert item["private"] == 1 and item["name"] == "download.bin"
        value = {"action": "read", "id": guid.replace("-", ""), "offset": 0}
        assert base64.b64decode((await files.execute(value))["data"]) == data
        path.unlink(); path.symlink_to(tmp_path / "other")
        (tmp_path / "other").write_bytes(b"secret")
        with pytest.raises(OSError):
            await files.execute(value)
        path.unlink();path.write_bytes(data)
        ack = {"action": "ack", "id": item["id"], "sha256": item["sha256"]}
        assert await files.execute(ack) == await files.execute(ack) == {"saved": True}
        assert not (await files.execute({"action": "list"}))["downloads"]
        await files.close()
    asyncio.run(scenario())


def test_retired_guest_recovers_final_rename_but_never_partial_download(tmp_path):
    async def scenario():
        files = guest.Files(tmp_path / "files", "a" * 32)
        completed, partial = str(uuid4()), str(uuid4())
        for guid in (completed, partial):
            await files.event({"method": "Browser.downloadWillBegin", "params": {"guid": guid, "suggestedFilename": "example.bin"}})
        (files.downloads / completed).write_bytes(b"final bytes")
        (files.downloads / (partial + ".crdownload")).write_bytes(b"partial bytes")
        (files.uploads / "retired-staging").write_bytes(b"unneeded original copy")
        await files.recover_downloads()
        listing = await files.execute({"action": "list"})
        assert len(listing["downloads"]) == 1 and listing["downloads"][0]["id"] == completed.replace("-", "")
        assert not list(files.uploads.iterdir()) and not (files.downloads / (partial + ".crdownload")).exists()
        assert files.db.execute("SELECT state FROM downloads WHERE guid=?", (partial,)).fetchone()[0] == "cancelled"
        await files.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("name", ["uploads", "downloads", "files.sqlite3"])
def test_guest_refuses_symlinked_storage_before_reading_files(tmp_path, name):
    root = tmp_path / "files"; root.mkdir(mode=0o700)
    destination = tmp_path / "private"
    if name.endswith("sqlite3"):
        destination.write_bytes(b"not a browser database")
    else:
        destination.mkdir(mode=0o700)
    (root / name).symlink_to(destination)
    with pytest.raises((ValueError, OSError)):
        guest.Files(root, "a" * 32)


def test_incomplete_and_changed_staged_uploads_do_not_reach_the_website(tmp_path):
    async def scenario():
        files = guest.Files(tmp_path / "files", "a" * 32)
        files.chooser = {"id": "b" * 32, "session": "target", "node": 1}
        async def state(): return {"id": "b" * 32, "destination": "https://example.org/upload"}
        files.chooser_state = state
        data = b"correct bytes"
        value = {"action": "begin", "id": "c" * 32, "chooser": "b" * 32, "destination": "https://example.org/upload",
            "name": "example.txt", "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        await files.execute(value)
        with pytest.raises(ValueError, match="upload_incomplete"):
            await files.execute({"action": "commit", "id": "c" * 32})
        await files.execute({"action": "write", "id": "c" * 32, "offset": 0, "data": base64.b64encode(b"changed bytes").decode()})
        with pytest.raises(ValueError, match="upload_incomplete"):
            await files.execute({"action": "commit", "id": "c" * 32})
        assert files.chooser is not None
        assert await files.execute({"action": "cancel", "chooser": "b" * 32}) == {"cancelled": True}
        assert files.chooser is None
        await files.close()
    asyncio.run(scenario())
