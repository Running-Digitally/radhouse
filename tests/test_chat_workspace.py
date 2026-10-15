"""Shared admission preserves selected models and explicit terminal excerpts."""
from copy import deepcopy
from uuid import uuid4
import json

from fastapi.testclient import TestClient
import pytest

from radhouse.chat.app import create_app
from radhouse.chat.service import ChatService
from radhouse.chat.store import ChatStore
from radhouse.domain.tasks import Rejected
from radhouse.integrations.hermes import HermesGatewayError, HermesInferenceAdmissionRejected, HermesRunsClient
import httpx
from tests.test_minimal_chat import SyntheticAuth, SyntheticHermes

HEADERS = {"Origin": "http://127.0.0.1", "X-Radhouse-CSRF": "synthetic-csrf",
           "X-Radhouse-Browser-Tab": str(uuid4())}


class Inference:
    def __init__(self):
        self.calls = []
        self.current = "fixture-alpha"
        self.offline = False

    def options(self, *, refresh=False):
        self.calls.append(("options", refresh))
        return {"state": "available", "models": [{"id": self.current}]}

    def resolve(self, choice):
        self.calls.append(("resolve", deepcopy(choice)))
        if self.offline:
            raise Rejected("inference_catalog_unavailable", 503)
        if choice["model"] != self.current:
            raise Rejected("inference_model_unavailable", 409)
        return {"provider": "fixture-engine", "model": choice["model"],
                "model_options": {"reasoning": {"enabled": True, "effort": "high"}}}


class Terminal:
    def __init__(self):
        self.calls = 0

    def scrub_context(self, _session, _tab, value):
        self.calls += 1
        return {**value, "text": value["text"].replace("synthetic-password", "[REDACTED]")}


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    # A real fixed Hermes HTTP client exercises the resulting dispatch payload.
    hermes = SyntheticHermes()
    inference, terminal = Inference(), Terminal()
    auth = SyntheticAuth()
    store = ChatStore(tmp_path / "chat.sqlite3")
    service = ChatService(store, hermes.client, owner_id="alice", clock=lambda: 1000)
    # Only Send integration needs the terminal stub; router tests own its HTTP contract.
    import radhouse.chat.owner_terminal as module
    from fastapi import APIRouter
    monkeypatch.setattr(module, "create_router", lambda *_: APIRouter())
    app = create_app(auth, service, inference=inference, owner_terminal=terminal)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        client.cookies.set(auth.cookie_name, "synthetic-cookie")
        yield client, service, hermes, inference, terminal, auth
    hermes.client.close()


def message(**extra):
    return {"request_id": str(uuid4()), "text": "Explain the result", "attachments": [], **extra}


def excerpt(text="captured output"):
    return {"kind": "terminal_excerpt", "label": "Agent VM terminal", "terminal_id": str(uuid4()),
        "generation": str(uuid4()), "captured_at": "2026-10-08T19:00:00Z", "source": "recent",
        "text": text, "truncated": False}


def test_retry_keeps_original_model_and_excerpt_without_new_catalog_or_capture(workspace):
    client, service, hermes, inference, terminal, _ = workspace
    body = message(inference={"model": "fixture-alpha", "thinking": "high"}, terminal_context=excerpt())
    hermes.lose_ack = True
    assert client.post("/chat/messages", json=body, headers=HEADERS).status_code == 503
    first = hermes.requests[0][1]
    assert first["provider"] == "fixture-engine" and first["model"] == "fixture-alpha"
    assert first["model_options"] == {"reasoning": {"enabled": True, "effort": "high"}}
    assert first["radhouse_inference"] is True
    assert "captured output" in first["input"] and "not a live terminal" in first["input"]
    assert first["disable_tools"] is True
    inference.current, inference.offline = "fixture-beta", True
    before = len(inference.calls), terminal.calls
    result = client.post("/chat/messages", json=body, headers=HEADERS)
    assert result.status_code == 200
    assert (len(inference.calls), terminal.calls) == before
    assert hermes.requests[1][1] == first and hermes.requests[1][0] == hermes.requests[0][0]
    turn = result.json()["turns"][0]
    assert turn["inference"] == body["inference"] and turn["terminal_context"] == body["terminal_context"]
    reopened = ChatService(ChatStore(service.store.path), hermes.client, owner_id="alice", clock=lambda: 1001)
    assert reopened.retry("alice", body["request_id"])["accepted_request_id"] == body["request_id"]
    assert len(hermes.requests) == 2


@pytest.mark.parametrize("field", ["inference", "terminal_context"])
def test_request_id_cannot_change_settings_or_shared_excerpt(workspace, field):
    client, _, hermes, _, _, _ = workspace
    body = message(inference={"model": "fixture-alpha", "thinking": "high"}, terminal_context=excerpt())
    assert client.post("/chat/messages", json=body, headers=HEADERS).status_code == 200
    edited = deepcopy(body)
    edited[field]["thinking" if field == "inference" else "text"] = "low" if field == "inference" else "later output"
    response = client.post("/chat/messages", json=edited, headers=HEADERS)
    assert response.status_code == 409 and response.json()["error"] == "message_options_changed"
    assert len(hermes.requests) == 1


def test_terminal_secret_is_scrubbed_before_any_durable_chat_storage(workspace):
    client, service, hermes, _, terminal, _ = workspace
    body = message(terminal_context=excerpt("synthetic-password"))
    assert client.post("/chat/messages", json=body, headers=HEADERS).status_code == 200
    saved = service.store.find("alice", body["request_id"])
    assert "synthetic-password" not in saved["request_options"] + saved["input_text"]
    assert "[REDACTED]" in saved["input_text"] and terminal.calls == 1
    assert "synthetic-password" not in json.dumps(hermes.requests)


def test_default_needs_no_catalog_and_no_terminal(workspace):
    client, _, hermes, inference, terminal, _ = workspace
    inference.offline = True
    response = client.post("/chat/messages", json=message(), headers=HEADERS)
    assert response.status_code == 200 and inference.calls == [] and terminal.calls == 0
    assert not {"model", "provider", "model_options", "radhouse_inference"} & hermes.requests[0][1].keys()


def test_catalog_rejection_is_before_reserved_turn(workspace):
    client, service, hermes, _, _, _ = workspace
    body = message(inference={"model": "disappeared-model", "thinking": "default"})
    response = client.post("/chat/messages", json=body, headers=HEADERS)
    assert response.status_code == 409
    assert service.store.find("alice", body["request_id"]) is None and hermes.requests == []


def test_catalog_refresh_requires_owner_auth_and_forwards_explicit_refresh(workspace):
    client, _, _, inference, _, auth = workspace
    assert client.get("/chat/inference?refresh=true").status_code == 200
    assert inference.calls == [("options", True)]
    auth.principal = "someone-else"
    assert client.get("/chat/inference").status_code == 403
    assert len(inference.calls) == 1


def test_new_pages_are_first_class_without_initializing_terminal(workspace):
    client, _, _, _, terminal, _ = workspace
    for path in ("/terminal", "/about-you"):
        response = client.get(path)
        assert response.status_code == 200 and 'id="terminal-link"' in response.text
        assert 'id="about-you-link"' in response.text
    assert terminal.calls == 0


@pytest.mark.parametrize("error", [[], {}, 12, None, True, "unknown_error"])
def test_malformed_native_rejection_is_uncertain_not_positive_no_admission(error):
    with HermesRunsClient("http://127.0.0.1", "synthetic", transport=httpx.MockTransport(
            lambda _: httpx.Response(409, json={"error": error, "admitted": False}))) as client:
        with pytest.raises(HermesGatewayError) as caught:
            client.start_or_attach(input_text="Question", session_id="fixture-session", dispatch_key="fixture-request",
                                  disable_tools=True, model="fixture-alpha", provider="fixture-engine")
        assert not isinstance(caught.value, HermesInferenceAdmissionRejected)


def test_fixed_no_admission_proof_closes_saved_turn_for_another_message(tmp_path):
    with HermesRunsClient("http://127.0.0.1", "synthetic", transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"features": {
                "runs_idempotency": {"supported": True, "durable": True, "retention_seconds": 3600},
                "runs_disable_tools": {"supported": True}}}) if request.url.path.endswith("capabilities") else
                httpx.Response(409, json={"error": "inference_model_unavailable", "admitted": False}))) as client:
        service = ChatService(ChatStore(tmp_path / "chat.sqlite3"), client, owner_id="alice", clock=lambda: 1000)
        request = str(uuid4())
        with pytest.raises(Rejected) as caught:
            service.send("alice", request, "Question", request_options={
                "selection": {"model": "fixture-alpha", "thinking": "default"},
                "runtime": {"provider": "fixture-engine", "model": "fixture-alpha"}})
        assert caught.value.code == "inference_model_unavailable"
        assert service.store.find("alice", request)["status"] == "failed"
        assert service.store.pending("alice") is None
