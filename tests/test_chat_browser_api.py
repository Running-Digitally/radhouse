"""Authenticated observer routes discard frames when login or run scope changes."""
import pytest
from fastapi.testclient import TestClient

from radhouse.chat.app import create_app
from radhouse.chat.browser import BrowserService
from radhouse.chat.service import ChatService
from radhouse.chat.store import ChatStore
from tests.test_chat_browser import JPEG, Relay, Store
from tests.test_minimal_chat import SyntheticAuth


@pytest.fixture
def api(tmp_path):
    auth, store, relay = SyntheticAuth(), Store(), Relay()
    browser = BrowserService(store, relay, owner_id="alice")
    chat = ChatService(ChatStore(tmp_path / "chat.sqlite3"), None, owner_id="alice")
    with TestClient(create_app(auth, chat, browser=browser), base_url="http://127.0.0.1") as client:
        yield client, auth, store, relay


@pytest.mark.parametrize("path", ["/chat/browser", "/chat/browser/frame?run_id=run-1"])
def test_authentication_precedes_store_and_private_network(api, path):
    client, _, store, relay = api
    response = client.get(path)
    assert response.status_code == 401
    assert response.json() == {"error": "authentication_required"}
    assert store.owners == relay.calls == []


@pytest.mark.parametrize("path", ["/chat/browser", "/chat/browser/frame?run_id=run-1"])
def test_foreign_authenticated_owner_is_denied_before_network(api, path):
    client, auth, store, relay = api
    auth.principal = "mallory"
    client.cookies.set(auth.cookie_name, "synthetic-cookie")
    response = client.get(path)
    assert response.status_code == 403
    assert response.json() == {"error": "owner_access_required"}
    assert store.owners == relay.calls == []


def test_authenticated_status_and_jpeg_have_private_cache_headers(api):
    client, auth, _, _ = api
    client.cookies.set(auth.cookie_name, "synthetic-cookie")
    status = client.get("/chat/browser")
    assert status.status_code == 200
    assert status.json() == {"state": "live", "run_id": "run-1", "generation": "generation-1", "url": "https://example.org/page"}
    assert "session-1" not in status.text
    response = client.get("/chat/browser/frame?run_id=run-1")
    assert response.status_code == 200
    assert response.content == JPEG
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["x-radhouse-browser-generation"] == "generation-1"
    assert response.headers["x-radhouse-browser-frame-id"] == "frame-1"
    assert float(response.headers["x-radhouse-browser-received-at"]) == 1000
    assert "x-radhouse-browser-captured-at" not in response.headers
    assert response.headers["cache-control"] == status.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_foreign_requested_run_is_denied_before_network(api):
    client, auth, _, relay = api
    client.cookies.set(auth.cookie_name, "synthetic-cookie")
    response = client.get("/chat/browser/frame?run_id=foreign-run")
    assert response.status_code == 409
    assert response.json() == {'error': 'browser_run_changed'}
    assert relay.calls == []


def test_frame_is_discarded_if_auth_is_revoked_during_upstream_read(api):
    client, auth, _, relay = api
    client.cookies.set(auth.cookie_name, "synthetic-cookie")
    relay.after = lambda: setattr(auth, "active", False)
    response = client.get("/chat/browser/frame?run_id=run-1")
    assert relay.calls == [("frame", "run-1")]
    assert response.status_code == 401
    assert response.json() == {'error': 'authentication_required'}
    assert JPEG not in response.content


def test_frame_is_discarded_if_run_finishes_during_upstream_read(api):
    client, auth, store, relay = api
    client.cookies.set(auth.cookie_name, "synthetic-cookie")
    relay.after = lambda: setattr(store, "run", None)
    response = client.get("/chat/browser/frame?run_id=run-1")
    assert response.status_code == 409
    assert response.json() == {'error': 'browser_run_changed'}
    assert JPEG not in response.content
