"""Library lists existing owner bytes, including unsent and legacy originals."""
import base64
import hashlib
import json
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from radhouse.chat.app import create_app
from radhouse.chat.attachments import Attachment
from radhouse.chat.service import ChatService
from radhouse.chat.store import ChatStore
from radhouse.domain.tasks import Rejected
from tests.test_minimal_chat import SyntheticAuth, SyntheticHermes


def upload(store, name, *, owner="alice", data=b"Original bytes\n"):
    file_id = str(uuid4())
    stream, path = store.begin_upload(owner, file_id, name)
    with stream:
        stream.write(data)
    return store.commit_upload(owner, file_id, name, path, "text/plain", "text",
        hashlib.sha256(data).hexdigest(), len(data))


def saved_turn(store, request_id, attachments, *, owner="alice", now=1000):
    turn = store.reserve(owner, request_id, "Read these", now, attachments)
    with store.connection() as db:
        db.execute("UPDATE turns SET status='completed',output='Done' WHERE seq=?", (turn["seq"],))
    return turn


def test_library_includes_unsent_uploads_deduplicates_sent_files_and_keeps_legacy(tmp_path):
    store = ChatStore(tmp_path / "chat.sqlite3")
    first = upload(store, "first.txt")
    saved_turn(store, "first-turn", (first, Attachment("old.txt", "text/plain", "text", b"Legacy bytes")))
    saved_turn(store, "second-turn", (first,), now=1001)
    unsent = upload(store, "unsent.txt")
    upload(store, "someone-else.txt", owner="bob")
    files = store.library("alice")["files"]
    assert [item["name"] for item in files] == ["unsent.txt", "first.txt", "old.txt"]
    assert files[0]["file_id"] == unsent.file_id and files[0]["created_at"] is None
    assert files[0]["request_id"] is None and files[0]["position"] is None
    assert files[1]["request_id"] == "first-turn" and files[1]["position"] == 0
    assert files[1]["created_at"] == 1000
    assert files[2]["file_id"] is None and files[2]["size"] == len(b"Legacy bytes")
    assert files[2]["download_url"] == "/chat/messages/first-turn/attachments/1"
    assert all(item["source"] == "user" for item in files)
    assert [item["name"] for item in store.library("bob")["files"]] == ["someone-else.txt"]
    assert not store.library("alice", source="assistant")["files"]
    assert first.data.read_bytes() == b"Original bytes\n"


def test_library_keyset_page_is_stable_when_new_upload_arrives(tmp_path):
    store = ChatStore(tmp_path / "chat.sqlite3")
    saved_turn(store, "legacy-1", (Attachment("legacy1.txt", "text/plain", "text", b"1"),))
    saved_turn(store, "legacy-2", (Attachment("legacy2.txt", "text/plain", "text", b"2"),))
    for number in range(4): upload(store, f"upload{number}.txt")
    first = store.library("alice", limit=2)
    assert [item["name"] for item in first["files"]] == ["upload3.txt", "upload2.txt"]
    upload(store, "new-arrival.txt")
    second = store.library("alice", before=first["next_cursor"], limit=2)
    third = store.library("alice", before=second["next_cursor"], limit=2)
    assert [item["name"] for item in second["files"]] == ["upload1.txt", "upload0.txt"]
    assert [item["name"] for item in third["files"]] == ["legacy2.txt", "legacy1.txt"]
    assert third["next_cursor"] is None
    ids = [item["id"] for page in (first, second, third) for item in page["files"]]
    assert len(ids) == len(set(ids)) == 6
    assert store.library("alice")["files"][0]["name"] == "new-arrival.txt"


@pytest.mark.parametrize("query,expected", [
    ("REPORT", ["Report.txt"]), ("%", ["100%_done.txt"]), ("_", ["100%_done.txt"]),
    ("100%_", ["100%_done.txt"]), ("STRASSE", ["Straße.txt"]), ("missing", [])])
def test_library_filename_search_is_case_insensitive_and_literal(tmp_path, query, expected):
    store = ChatStore(tmp_path / "chat.sqlite3")
    for name in ("Report.txt", "100%_done.txt", "100abcXdone.txt", "Straße.txt"):
        upload(store, name)
    assert [item["name"] for item in store.library("alice", query=query)["files"]] == expected


@pytest.mark.parametrize("cursor", ["!", "", "x" * 257,
    base64.urlsafe_b64encode(json.dumps([True, 1, 0]).encode()).decode(),
    base64.urlsafe_b64encode(json.dumps([0, 0, 0]).encode()).decode(),
    base64.urlsafe_b64encode(json.dumps([2, 1, 0]).encode()).decode(),
    base64.urlsafe_b64encode(json.dumps([0, 2**64, 0]).encode()).decode()])
def test_invalid_library_cursor_denied(tmp_path, cursor):
    with pytest.raises(Rejected, match="library_cursor_invalid"):
        ChatStore(tmp_path / "chat.sqlite3").library("alice", before=cursor)


def test_library_http_owner_authorization_and_original_download(tmp_path):
    store = ChatStore(tmp_path / "chat.sqlite3")
    item = upload(store, "available.txt", data=b"Exact downloadable bytes")
    legacy_request = str(uuid4())
    saved_turn(store, legacy_request, (Attachment("legacy.txt", "text/plain", "text", b"Old original"),))
    runtime, auth = SyntheticHermes(), SyntheticAuth()
    service = ChatService(store, runtime.client, owner_id="alice")
    client = TestClient(create_app(auth, service))
    try:
        assert client.get("/chat/library").status_code == 401
        client.cookies.set(auth.cookie_name, "synthetic-cookie")
        response = client.get("/chat/library")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        files = response.json()["files"]
        assert client.get(files[0]["download_url"]).content == b"Exact downloadable bytes"
        assert client.get(files[1]["download_url"]).content == b"Old original"
        assert client.get("/chat/library", params={"source": "bogus"}).status_code == 422
        assert client.get("/chat/library", params={"before": "x" * 257}).status_code == 422
        assert client.get("/chat/library", params={"query": "x" * 513}).status_code == 422
        auth.principal = "bob"
        assert client.get("/chat/library").status_code == 403
        assert client.get("/chat/files/" + item.file_id + "/content").status_code == 403
        auth.principal = "alice"
        other = upload(store, "private.txt", owner="bob")
        assert client.get("/chat/files/" + other.file_id + "/content").status_code == 404
    finally:
        client.close()
        runtime.client.close()


def test_library_preserves_schema3_and_eight_column_upload_insert(tmp_path):
    store = ChatStore(tmp_path / "chat.sqlite3")
    original = upload(store, "original.txt")
    reopened = ChatStore(store.path)
    with reopened.connection() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 3
        assert len(db.execute("PRAGMA table_info(uploads)").fetchall()) == 8
    assert reopened.library("alice")["files"][0]["file_id"] == original.file_id
