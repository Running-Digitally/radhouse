"""Current-owner, current-run browser observation; no native browser is created."""
from dataclasses import replace
import base64
import math

import httpx
import pytest

from radhouse.chat.browser import (
    BROWSER_TOOLS, MAX_FRAME_BYTES, BrowserFrame, BrowserService, BrowserStatus,
    HermesBrowserClient,
)
from radhouse.chat.store import ChatStore
from radhouse.domain.tasks import Rejected
from radhouse.integrations.hermes import HermesGatewayError


JPEG = b"\xff\xd8\xff\xe0synthetic-jpeg\xff\xd9"


class Store:
    def __init__(self):
        self.run = {"request_id": "request-1", "run_id": "run-1", "session_id": "session-1",
                    "allowed_tools": BROWSER_TOOLS, "status": "running"}
        self.owners = []

    def browser_run(self, owner):
        self.owners.append(owner)
        return None if self.run is None else dict(self.run)


class Relay:
    def __init__(self):
        self.status = BrowserStatus("run-1", "session-1", "live", "generation-1", "https://example.org/page")
        self.frame = BrowserFrame(JPEG, "generation-1", "frame-1", 1000.0, "run-1", "session-1")
        self.calls = []
        self.after = lambda: None
        self.error = None

    def browser_status(self, run_id):
        self.calls.append(("status", run_id))
        self.after()
        if self.error:
            raise self.error
        return self.status

    def browser_frame(self, run_id):
        self.calls.append(("frame", run_id))
        self.after()
        if self.error:
            raise self.error
        return self.frame


@pytest.fixture
def observer():
    store, relay = Store(), Relay()
    return BrowserService(store, relay, owner_id="alice"), store, relay


@pytest.mark.parametrize("operation", ["status", "frame"])
def test_foreign_owner_denied_before_store_or_network(observer, operation):
    service, store, relay = observer
    action = service.status if operation == "status" else service.frame
    arguments = ("mallory",) if operation == "status" else ("mallory", "run-1")
    with pytest.raises(Rejected, match="owner_access_required") as error:
        action(*arguments)
    assert error.value.status == 403
    assert store.owners == relay.calls == []


@pytest.mark.parametrize("tools", [(), ("browser_navigate",), (*BROWSER_TOOLS, "shell"),
                                    (*BROWSER_TOOLS, "browser_exec"), (*BROWSER_TOOLS, "browser_navigate"),
                                    list(BROWSER_TOOLS), (*BROWSER_TOOLS, [])])
def test_missing_or_expanded_tool_scope_denied_before_network(observer, tools):
    service, store, relay = observer
    store.run["allowed_tools"] = tools
    with pytest.raises(Rejected, match="browser_scope_unavailable"):
        service.status("alice")
    with pytest.raises(Rejected, match="browser_scope_unavailable"):
        service.frame("alice", "run-1")
    assert relay.calls == []


def test_document_tools_can_coexist_without_expanding_browser_scope(observer):
    service, store, _ = observer
    store.run["allowed_tools"] += ("document_search", "document_read")
    assert service.status("alice")["state"] == "live"


def test_starting_and_idle_need_no_network(observer):
    service, store, relay = observer
    store.run.update(status="awaiting_dispatch", run_id=None)
    assert service.status("alice") == {"state": "starting", "run_id": None, "generation": None, "url": None}
    with pytest.raises(Rejected, match="browser_run_changed"):
        service.frame("alice", "run-1")
    store.run = None
    assert service.status("alice") == {"state": "idle", "run_id": None, "generation": None, "url": None}
    assert relay.calls == []


@pytest.mark.parametrize("run_id", ["old-run", "run-1/../../secret", "", None])
def test_requested_run_must_match_durable_current_run_before_network(observer, run_id):
    service, _, relay = observer
    with pytest.raises(Rejected, match="browser_run_changed"):
        service.frame("alice", run_id)
    assert relay.calls == []


@pytest.mark.parametrize("field", ["run_id", "session_id"])
def test_upstream_identity_mismatch_returns_no_frame_or_private_details(observer, field):
    service, _, relay = observer
    relay.status = replace(relay.status, **{field: "foreign-secret"})
    relay.frame = replace(relay.frame, **{field: "foreign-secret"})
    status = service.status("alice")
    assert status == {"state": "unavailable", "run_id": "run-1", "generation": None, "url": None}
    with pytest.raises(Rejected, match="^browser_unavailable$"):
        service.frame("alice", "run-1")
    assert "foreign-secret" not in str(status)


@pytest.mark.parametrize("change", ["terminal", "new_run", "new_session", "new_request", "tool_scope"])
def test_late_response_is_discarded_when_current_scope_changes(observer, change):
    service, store, relay = observer
    before = dict(store.run)

    def alter():
        if change == "terminal":
            store.run = None
        elif change == "tool_scope":
            store.run["allowed_tools"] += ("document_search",)
        else:
            key = {"new_run": "run_id", "new_session": "session_id", "new_request": "request_id"}[change]
            store.run[key] = "replacement-1"

    relay.after = alter
    assert service.status("alice")["state"] == "idle"
    store.run = dict(before)
    with pytest.raises(Rejected, match="browser_run_changed"):
        service.frame("alice", "run-1")


def test_recreated_service_observes_same_saved_run_without_starting_browser(observer):
    _, store, relay = observer
    reopened = BrowserService(store, relay, owner_id="alice")
    assert reopened.status("alice")["generation"] == "generation-1"
    assert reopened.frame("alice", "run-1").jpeg == JPEG
    assert relay.calls == [("status", "run-1"), ("frame", "run-1")]


def test_restart_uses_durable_browser_tool_policy_and_session(tmp_path):
    store = ChatStore(tmp_path / "chat.sqlite3")
    turn = store.reserve("alice", "request-1", "Use the browser", 1000, 3600)
    store.select_tools(turn, BROWSER_TOOLS)
    with store.connection() as db:
        db.execute("UPDATE turns SET run_id='run-1',status='running' WHERE request_id='request-1'")
    saved = store.browser_run("alice")
    relay = Relay()
    relay.status = replace(relay.status, session_id=saved["session_id"])
    relay.frame = replace(relay.frame, session_id=saved["session_id"])
    reopened = ChatStore(store.path)
    observer = BrowserService(reopened, relay, owner_id="alice")
    assert reopened.browser_run("alice") == saved
    assert observer.status("alice")["state"] == "live"
    assert observer.frame("alice", "run-1").jpeg == JPEG
    with reopened.connection() as db:
        db.execute("UPDATE turns SET status='completed' WHERE request_id='request-1'")
    assert observer.status("alice")["state"] == "idle"
    with pytest.raises(Rejected, match="browser_run_changed"):
        observer.frame("alice", "run-1")
    assert relay.calls == [("status", "run-1"), ("frame", "run-1")]


def test_gateway_failure_is_sanitized(observer):
    service, _, relay = observer
    relay.error = HermesGatewayError("vendor_cookie_or_token_detail")
    assert service.status("alice")["state"] == "unavailable"
    with pytest.raises(Rejected, match="^browser_unavailable$"):
        service.frame("alice", "run-1")


def payload(**changes):
    return {"run_id": "run-1", "session_id": "session-1", "generation": "generation-1",
            "frame_id": "frame-1", "received_at": 1000, "captured_at": None,
            "jpeg": base64.b64encode(JPEG).decode(), **changes}


def client_for(data, requests=None, **response):
    def respond(request):
        if requests is not None:
            requests.append(request)
        return httpx.Response(response.pop("status", 200), json=data, **response)
    return HermesBrowserClient("http://127.0.0.1:8642", "synthetic-only", transport=httpx.MockTransport(respond), clock=lambda: 1000)


def test_transport_uses_fixed_private_relay_and_bounded_wire():
    requests = []
    client = client_for(payload(), requests)
    try:
        frame = client.browser_frame("run-1")
        assert frame.jpeg == JPEG
        assert frame.received_at == 1000.0
        assert frame.captured_at is None
        assert str(requests[0].url) == "http://127.0.0.1:8642/v1/runs/run-1/browser-frame"
        assert requests[0].method == "GET"
        assert requests[0].headers["authorization"] == "Bearer synthetic-only"
        assert requests[0].content == b""
        with pytest.raises(HermesGatewayError, match="browser_response_invalid"):
            client.browser_frame("../foreign")
        assert len(requests) == 1
    finally:
        client.close()


@pytest.mark.parametrize("change", [
    {"jpeg": "%%%"}, {"jpeg": ""}, {"jpeg": base64.b64encode(b"<html>secret</html>").decode()},
    {"jpeg": base64.b64encode(b"\xff\xd8\xff" + b"x" * MAX_FRAME_BYTES + b"\xff\xd9").decode()},
    {"received_at": True}, {"received_at": -1}, {"received_at": 1031}, {"received_at": 10**400},
    {"received_at": "1000"}, {"captured_at": 1000},
    {"run_id": "../../secret"}, {"run_id": "foreign-run"}, {"session_id": None},
    {"generation": None}, {"frame_id": "has spaces"},
])
def test_malformed_or_oversized_frame_rejected(change):
    client = client_for(payload(**change))
    try:
        with pytest.raises(HermesGatewayError, match="browser_response_invalid"):
            client.browser_frame("run-1")
    finally:
        client.close()


@pytest.mark.parametrize("received", [math.nan, math.inf, -math.inf])
def test_nonfinite_frame_time_rejected(received):
    client = client_for(payload())
    client._runs._request = lambda *a, **kw: (payload(received_at=received), {})
    try:
        with pytest.raises(HermesGatewayError, match="browser_response_invalid"):
            client.browser_frame("run-1")
    finally:
        client.close()


def test_status_exposes_safe_url_without_query_or_fragment():
    client = client_for({"run_id": "run-1", "session_id": "session-1", "state": "live",
                         "generation": "generation-1", "url": "https://example.org/page?token=private#secret"})
    try:
        assert client.browser_status("run-1").url == "https://example.org/page"
    finally:
        client.close()


@pytest.mark.parametrize("url", ["https://user:secret@example.org/", "file:///private/secret", "javascript:alert(1)",
                                 "https:///no-host", "https://example.org:invalid/", "https://example.org/\nsecret"])
def test_credentialed_or_non_http_display_url_rejected(url):
    client = client_for({"run_id": "run-1", "session_id": "session-1", "state": "live",
                         "generation": "generation-1", "url": url})
    try:
        with pytest.raises(HermesGatewayError, match="browser_response_invalid"):
            client.browser_status("run-1")
    finally:
        client.close()


@pytest.mark.parametrize("url", ["http://192.168.50.65:8443/", "http://lucy.lan/", "http://builder/", "http://[::1]/"])
def test_display_url_does_not_replace_vm_firewall_policy(url):
    client = client_for({"run_id": "run-1", "session_id": "session-1", "state": "live",
                         "generation": "generation-1", "url": url})
    try:
        assert client.browser_status("run-1").url == url
    finally:
        client.close()


def test_redirect_is_not_followed():
    requests = []
    client = client_for({}, requests, status=302, headers={"Location": "http://192.168.50.65/secret"})
    try:
        with pytest.raises(HermesGatewayError):
            client.browser_frame("run-1")
        assert len(requests) == 1
    finally:
        client.close()
