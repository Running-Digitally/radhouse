"""Owner preferences persist without changing network or runtime authority."""
from fastapi.testclient import TestClient
import pytest

from radhouse.chat.app import create_app
from radhouse.chat.store import ChatStore
from radhouse.domain.tasks import Rejected
from tests.test_minimal_chat import chat, SyntheticAuth


def test_saved_preference_restart_conflict_and_replay(chat):
    service, _ = chat; store = service.store
    assert store.browser_preferences("alice")["search_engine"] == "google"
    result = store.save_browser_preferences("alice", 0, "duckduckgo")
    assert result["revision"] == 1
    assert ChatStore(store.path).browser_preferences("alice") == result
    assert store.save_browser_preferences("alice", 0, "duckduckgo") == result
    with pytest.raises(Rejected, match="browser_preferences_changed"):
        store.save_browser_preferences("alice", 0, "google")
    assert store.browser_preferences("other")["search_engine"] == "google"


def test_history_is_owner_scoped_bounded_and_excludes_parameters(chat):
    store = chat[0].store
    for i in range(50):
        store.record_browser_visit("alice", f"https://example.org/{i}?secret=hidden#fragment", i)
    store.record_browser_visit("other", "https://other.example/", 1)
    store.record_browser_visit("alice", "https://alice:password@example.org/", 51)
    history = store.browser_preferences("alice")["history"]
    assert len(history) == 40 and history[0]["url"] == "https://example.org/49"
    assert all("?" not in item["url"] and "#" not in item["url"] for item in history)
    store.clear_browser_history("alice")
    assert not store.browser_preferences("alice")["history"]
    assert store.browser_preferences("other")["history"]


def test_preferences_api_enforces_auth_owner_origin_csrf_and_strict_choice(chat):
    service, _ = chat; auth = SyntheticAuth()
    with TestClient(create_app(auth, service), base_url="http://127.0.0.1") as client:
        assert client.get("/chat/browser/preferences").status_code == 401
        client.cookies.set(auth.cookie_name, "synthetic-cookie")
        body = {"revision": 0, "search_engine": "duckduckgo"}
        assert client.post("/chat/browser/preferences", json=body).status_code == 403
        headers = {"Origin": "http://127.0.0.1", "X-Radhouse-CSRF": "synthetic-csrf"}
        assert client.post("/chat/browser/preferences", json=body, headers=headers).status_code == 200
        assert client.post("/chat/browser/preferences", json={**body, "search_engine": "arbitrary"}, headers=headers).status_code == 422
        auth.principal = "other"
        assert client.get("/chat/browser/preferences").status_code == 403
        assert client.post("/chat/browser/history/clear", json={}, headers=headers).status_code == 403
        auth.principal = "alice"
        assert client.post("/chat/browser/history/clear", json={}, headers=headers).status_code == 200
