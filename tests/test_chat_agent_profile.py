"""Saved presentation stays owner-scoped, durable and separate from chat work."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from radhouse.chat.agent_profile import AgentProfileBody, DEFAULT_PROFILE, portrait_themes
from radhouse.chat.app import create_app
from radhouse.chat.service import ChatService
from radhouse.chat.store import ChatStore
from radhouse.domain.tasks import Rejected
from tests.test_minimal_chat import SyntheticAuth, SyntheticHermes


HEADERS = {"Origin": "http://127.0.0.1", "X-Radhouse-CSRF": "synthetic-csrf"}


@pytest.fixture
def profile_app(tmp_path):
    auth, hermes = SyntheticAuth(), SyntheticHermes()
    store = ChatStore(tmp_path / "chat.sqlite3")
    service = ChatService(store, hermes.client, owner_id="alice", clock=lambda: 1000)
    with TestClient(create_app(auth, service), base_url="http://127.0.0.1") as client:
        client.cookies.set(auth.cookie_name, "synthetic-cookie")
        yield client, store, service, auth, hermes
    hermes.client.close()


def post(client, body, headers=HEADERS):
    # JSON escapes also exercise rejected surrogate codepoints without Python's UTF-8 encoder intervening.
    return client.post("/chat/agent-profile", content=json.dumps(body),
        headers={"Content-Type": "application/json", **headers})


def saved(**changes):
    return {**DEFAULT_PROFILE, "name": "My assistant", "intro": "A little help.",
        "theme": "kiln", "portrait": "miro", "accent": "clay", "surface": "system", **changes}


def table_rows(store):
    with store.connection() as db:
        names = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name!='agent_profiles'")]
        return {name: [tuple(row) for row in db.execute('SELECT * FROM "' + name + '" ORDER BY rowid')]
            for name in names}


def test_default_get_does_not_write_or_create_conversation_or_call_hermes(profile_app):
    client, store, service, _, hermes = profile_app
    before = table_rows(store)
    response = client.get("/chat/agent-profile")
    assert response.status_code == 200 and response.json() == DEFAULT_PROFILE
    assert response.headers["cache-control"] == "no-store"
    with store.connection() as db:
        assert db.execute("SELECT count(*) FROM agent_profiles").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM conversations").fetchone()[0] == 0
    assert table_rows(store) == before
    assert service.owner_id == "alice" and hermes.requests == []


def test_saved_full_profile_survives_reopen_without_chat(profile_app):
    client, store, service, _, hermes = profile_app
    draft = saved(name="  Ari  ", intro="  Let's try <something> together.  ", stateMotion=False)
    response = post(client, draft)
    expected = {**draft, "name": "Ari", "intro": "Let's try <something> together.", "revision": 1}
    assert response.status_code == 200 and response.json() == expected
    assert client.get("/chat/agent-profile").json() == expected
    reopened = ChatStore(store.path)
    assert reopened.agent_profile("alice") == expected
    with reopened.connection() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 3
        assert db.execute("SELECT count(*) FROM conversations").fetchone()[0] == 0
    assert service.owner_id == "alice" and hermes.requests == []


def test_distinct_authorized_owners_get_only_their_record(profile_app):
    client, store, _, _, hermes = profile_app
    assert post(client, saved(name="Alice only")).status_code == 200
    bob_auth = SyntheticAuth(); bob_auth.principal = "bob"
    bob_service = ChatService(store, hermes.client, owner_id="bob")
    with TestClient(create_app(bob_auth, bob_service), base_url="http://127.0.0.1") as bob:
        bob.cookies.set(bob_auth.cookie_name, "synthetic-cookie")
        assert bob.get("/chat/agent-profile").json() == DEFAULT_PROFILE
        assert post(bob, saved(name="Bob only")).status_code == 200
        assert bob.get("/chat/agent-profile").json()["name"] == "Bob only"
    assert client.get("/chat/agent-profile").json()["name"] == "Alice only"
    assert hermes.requests == []


@pytest.mark.parametrize("method", ["get", "post"])
@pytest.mark.parametrize("denial", ["logged_out", "other_owner", "no_cookie"])
def test_authentication_or_owner_denial_before_store_access(profile_app, monkeypatch, method, denial):
    client, store, _, auth, _ = profile_app
    calls = []
    monkeypatch.setattr(store, "agent_profile", lambda *_: calls.append("get"))
    monkeypatch.setattr(store, "save_agent_profile", lambda *_: calls.append("post"))
    if denial == "logged_out": auth.active = False
    if denial == "other_owner": auth.principal = "bob"
    if denial == "no_cookie": client.cookies.clear()
    response = client.get("/chat/agent-profile") if method == "get" else post(client, saved())
    assert response.status_code == (403 if denial == "other_owner" else 401)
    assert response.json() == {"error": "owner_access_required" if denial == "other_owner" else "authentication_required"}
    assert calls == []


@pytest.mark.parametrize("headers,code", [
    ({}, "request_origin_denied"),
    ({"Origin": "https://evil.example", "X-Radhouse-CSRF": "synthetic-csrf"}, "request_origin_denied"),
    ({"Origin": "http://127.0.0.1"}, "csrf_denied"),
    ({"Origin": "http://127.0.0.1", "X-Radhouse-CSRF": "wrong"}, "csrf_denied"),
])
def test_save_requires_existing_origin_and_csrf_checks(profile_app, headers, code):
    client, store, _, _, _ = profile_app
    response = post(client, saved(), headers)
    assert response.status_code == 403 and response.json() == {"error": code}
    assert store.agent_profile("alice") == DEFAULT_PROFILE


@pytest.mark.parametrize("change", [
    {"schema": "radhouse.agent-profile.v2"}, {"schema_": "radhouse.agent-profile.v1"},
    {"owner": "bob"}, {"agent_id": "other-agent"}, {"prompt": "change the agent"},
    {"state": "working"}, {"asset": "https://example.test/evil.webp"},
    {"name": "n" * 33}, {"intro": "i" * 161}, {"name": None}, {"intro": 12},
    {"name": "A\x00secret"}, {"name": "Line\nTwo"}, {"intro": "Tab\ttext"},
    {"name": "A\ud800"}, {"intro": "A\u2028line"}, {"name": "B\u202esecret"},
    {"revision": -1}, {"revision": True}, {"revision": 0.0}, {"revision": "0"},
    {"revision": 2**63 - 1}, {"stateMotion": 1}, {"iconMotion": "true"},
    {"theme": "missing"}, {"theme": "signal", "portrait": "ember"},
    {"portrait": "../../private"}, {"portrait": "data:image/webp;base64,evil"},
    {"accent": "custom"}, {"surface": "unrecognized"},
])
def test_strict_invalid_body_is_not_saved_or_echoed(profile_app, change):
    client, store, _, _, hermes = profile_app
    response = post(client, saved(**change))
    assert response.status_code == 422 and response.json() == {"error": "invalid_request"}
    assert store.agent_profile("alice") == DEFAULT_PROFILE
    assert hermes.requests == []


@pytest.mark.parametrize("field", list(DEFAULT_PROFILE))
def test_save_requires_full_profile_including_schema_and_revision(profile_app, field):
    client, store, _, _, _ = profile_app
    body = saved(); body.pop(field)
    response = post(client, body)
    assert response.status_code == 422 and response.json() == {"error": "invalid_request"}
    assert store.agent_profile("alice") == DEFAULT_PROFILE


def test_plain_unicode_and_markup_like_text_round_trip_as_text(profile_app):
    client, _, _, _, _ = profile_app
    body = saved(name="<img src=x onerror=evil()>", intro="مرحبا 👩‍💻 <script>evil()</script>")
    response = post(client, body)
    assert response.status_code == 200
    assert response.json() == {**body, "revision": 1}
    assert client.get("/chat/agent-profile").json() == response.json()
    assert post(client, saved(name="  " + "界" * 32 + "  ", revision=1)).status_code == 200


@pytest.mark.parametrize("linebreak", ["\n", "\r\n", "\r"])
def test_multiline_intro_round_trips_with_normalized_linebreaks(profile_app, linebreak):
    client, store, _, _, hermes = profile_app
    body = saved(intro="  First thought" + linebreak + "Second thought  ")
    response = post(client, body)
    assert response.status_code == 200
    assert response.json()["intro"] == "First thought\nSecond thought"
    assert client.get("/chat/agent-profile").json() == response.json()
    assert ChatStore(store.path).agent_profile("alice") == response.json()
    assert hermes.requests == []


@pytest.mark.parametrize("field,value", [
    ("name", "First\nSecond"), ("name", "First\r\nSecond"),
    ("name", "First\rSecond"), ("name", "First\tSecond"),
    ("intro", "First\nSecond\tThird"),
])
def test_linebreaks_remain_intro_only_and_tabs_are_rejected(profile_app, field, value):
    client, store, _, _, _ = profile_app
    response = post(client, saved(**{field: value}))
    assert response.status_code == 422 and response.json() == {"error": "invalid_request"}
    assert store.agent_profile("alice") == DEFAULT_PROFILE


def test_stale_revision_returns_only_conflict_and_keeps_saved_record(profile_app):
    client, store, _, _, _ = profile_app
    response = post(client, saved(name="First tab"))
    assert response.status_code == 200
    stale = post(client, saved(name="Unsaved draft"))
    assert stale.status_code == 409 and stale.json() == {"error": "agent_profile_conflict"}
    assert store.agent_profile("alice")["name"] == "First tab"
    assert post(client, saved(name="Second save", revision=1)).json()["revision"] == 2


def test_concurrent_full_saves_have_one_winner_and_one_conflict(profile_app):
    _, store, _, _, _ = profile_app
    def save(name):
        try:
            return store.save_agent_profile("alice", AgentProfileBody.model_validate(saved(name=name)).presentation())
        except Rejected as error:
            return error.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, ("First tab", "Second tab")))
    assert sum(result == "agent_profile_conflict" for result in results) == 1
    winner = next(result for result in results if isinstance(result, dict))
    assert winner["revision"] == 1 and store.agent_profile("alice") == winner


def test_additive_table_and_saves_leave_existing_chat_files_and_options_intact(profile_app):
    client, store, service, _, hermes = profile_app
    file_id = str(uuid4()); raw = b"Immutable original"
    stream, path = store.begin_upload("alice", file_id, "original.txt")
    with stream: stream.write(raw)
    attachment = store.commit_upload("alice", file_id, "original.txt", path, "text/plain", "text", hashlib.sha256(raw).hexdigest(), len(raw))
    turn = store.reserve("alice", str(uuid4()), "A saved message", 1000, (attachment,))
    store.freeze_request_options(turn, {"selection": {"model": "saved-model", "thinking": "default"}})
    # Reopen a previous schema-3 store that predates the additive profile table.
    with store.connection() as db: db.execute("DROP TABLE agent_profiles")
    before = table_rows(store)
    reopened = ChatStore(store.path)
    assert table_rows(reopened) == before
    assert post(client, saved()).status_code == 200
    assert client.get("/chat/agent-profile").json()["revision"] == 1
    assert table_rows(reopened) == before
    assert reopened.upload("alice", file_id).data.read_bytes() == raw
    with reopened.connection() as db: assert db.execute("PRAGMA user_version").fetchone()[0] == 3
    assert service.owner_id == "alice" and hermes.requests == []


def test_fixed_catalog_and_portrait_routes_reject_paths_and_unlisted_assets(profile_app):
    client, _, _, _, _ = profile_app
    catalog = client.get("/workspace-assets/agent-profile/catalog.json")
    assert catalog.status_code == 200 and catalog.headers["content-type"].startswith("application/json")
    assert len(catalog.json()["profiles"]) == 13
    assert client.get("/agent").status_code == 200
    for name in portrait_themes():
        response = client.get("/workspace-assets/agent-profile/portraits/" + name + ".webp")
        assert response.status_code == 200 and response.headers["content-type"] == "image/webp"
        assert response.content[:4] == b"RIFF" and response.content[8:12] == b"WEBP"
    for path in ("/workspace-assets/agent-profile/portraits/unknown.webp",
                 "/workspace-assets/agent-profile/portraits/%2e%2e%2fsecret.webp",
                 "/workspace-assets/agent-profile/secret.json",
                 "/workspace-assets/private.js", "/workspace-assets/agent-profile/catalog.js"):
        assert client.get(path).status_code == 404


def test_missing_catalog_fails_closed_without_private_diagnostics(profile_app, monkeypatch, tmp_path):
    client, store, _, _, _ = profile_app
    import radhouse.chat.agent_profile as module
    portrait_themes.cache_clear()
    monkeypatch.setattr(module, "CATALOG_PATH", tmp_path / "private-catalog.json")
    try:
        response = post(client, saved())
        assert response.status_code == 503 and response.json() == {"error": "agent_profile_unavailable"}
        assert store.agent_profile("alice") == DEFAULT_PROFILE
    finally:
        portrait_themes.cache_clear()
