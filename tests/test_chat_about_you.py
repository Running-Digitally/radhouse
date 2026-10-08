"""Saved notes are owner-only reads, including while native I/O is in flight."""
from copy import deepcopy
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
import httpx
import pytest

from radhouse.chat.about_you import AboutYouService, create_router
from radhouse.domain.tasks import Rejected
from radhouse.integrations.hermes import HermesGatewayError, HermesRunsClient


def snapshot():
    return {"schema": "radhouse.saved-memory.v1", "checked_at": "2026-10-08T17:00:00+00:00",
        "sources": [{"target": target, "source_filename": filename, "state": "available",
            "entries": ["One complete\nmultiline note."], "file_modified_at": "2026-10-07T16:00:00+00:00",
            "complete": True} for target, filename in (("user", "USER.md"), ("memory", "MEMORY.md"))]}


def session(**changes):
    return SimpleNamespace(**({"principal_id": "alice", "conversation_id": "conversation-alice",
        "binding_revision": 1, "token": "synthetic-cookie"} | changes))


class Client:
    def __init__(self, value=None, after=None):
        self.value = value if value is not None else snapshot()
        self.after, self.calls = after, []

    def _request(self, method, path, *, expected_status):
        self.calls.append((method, path, expected_status))
        if self.after:
            self.after()
        if isinstance(self.value, Exception):
            raise self.value
        return deepcopy(self.value), {}


def app_for(native, auth):
    app = FastAPI()
    @app.exception_handler(Rejected)
    async def rejected(_request, error):
        return JSONResponse({"error": error.code}, status_code=error.status)
    app.include_router(create_router(AboutYouService(native, owner_id="alice"), auth))
    return app


def test_owner_can_read_complete_notes_and_exact_sources_without_chat():
    native = Client()
    with TestClient(app_for(native, lambda _request: session())) as client:
        response = client.get("/chat/about-you")
    assert response.status_code == 200
    assert response.json() == snapshot()
    assert response.headers["cache-control"] == "no-store"
    assert native.calls == [("GET", "v1/radhouse/memory", 200)]


def test_other_owner_is_rejected_before_any_native_read():
    native = Client()
    with TestClient(app_for(native, lambda _request: session(principal_id="bob"))) as client:
        response = client.get("/chat/about-you")
    assert response.status_code == 403
    assert native.calls == []


@pytest.mark.parametrize("change", ["logout", "principal_id", "conversation_id", "binding_revision", "token"])
def test_authentication_is_checked_again_after_native_read(change):
    active = [session()]
    def changed():
        active[0] = None if change == "logout" else session(**{change: 2 if change == "binding_revision" else "changed"})
    def authenticate(_request):
        if active[0] is None:
            raise Rejected("authentication_required", 401)
        return active[0]
    native = Client(after=changed)
    with TestClient(app_for(native, authenticate)) as client:
        response = client.get("/chat/about-you")
    assert response.status_code == (401 if change == "logout" else 403 if change == "principal_id" else 409)
    assert "multiline note" not in response.text


@pytest.mark.parametrize("value", [HermesGatewayError("private-profile-path"), {"private_config": "secret"}])
def test_native_failure_does_not_export_private_error_or_vendor_payload(value):
    with TestClient(app_for(Client(value), lambda _request: session())) as client:
        response = client.get("/chat/about-you")
    assert response.status_code == 503
    assert response.json() == {"error": "memory_unavailable"}
    assert "private" not in response.text and "secret" not in response.text


@pytest.mark.parametrize("mutate", [
    lambda value: value["sources"][0].update(source_filename=".env"),
    lambda value: value["sources"][0].update(entries=[], state="available"),
    lambda value: value["sources"][0].update(entries=None, state="unreadable", complete=True),
    lambda value: value["sources"][0].update(author="invented"),
])
def test_unbounded_or_invented_source_contract_is_rejected(mutate):
    value = snapshot(); mutate(value)
    with TestClient(app_for(Client(value), lambda _request: session())) as client:
        response = client.get("/chat/about-you")
    assert response.status_code == 503


def test_reader_uses_existing_native_client_transport_and_one_fixed_get():
    requests = []
    def respond(request):
        requests.append((request.method, request.url.path))
        return httpx.Response(200, json=snapshot())
    with HermesRunsClient("http://127.0.0.1", "synthetic-bearer", transport=httpx.MockTransport(respond)) as client:
        assert AboutYouService(client, owner_id="alice").snapshot(session()) == snapshot()
    assert requests == [("GET", "/v1/radhouse/memory")]
