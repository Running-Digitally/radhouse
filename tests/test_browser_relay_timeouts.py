"""Real HTTP acknowledgements outlive the short observer budget without replay."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import threading
import time

import httpx
import pytest

from radhouse.chat.browser import HermesBrowserClient
from radhouse.integrations.hermes import HermesGatewayError


INPUT = {"generation": "generation-1", "revision": 3, "lease_id": "lease-1",
    "sequence": 1, "operation": "navigate", "arguments": {"url": "https://example.org/"},
    "frame_id": "frame-1", "viewport": {"width": 960, "height": 540}}


@pytest.fixture
def loopback_gateway():
    requests = []
    settings = {"delay": 3.2, "disconnect": False}
    finished = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            try:
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                requests.append((self.path, body))
                if settings["disconnect"]:
                    self.connection.shutdown(socket.SHUT_RDWR)
                    return
                time.sleep(settings["delay"])
                reply = json.dumps({"outcome": "applied", "sequence": body.get("sequence")}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(reply)))
                self.end_headers()
                self.wfile.write(reply)
            except (BrokenPipeError, ConnectionResetError):
                pass  # The observer deliberately stops waiting before the delayed reply.
            finally:
                finished.set()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests, settings
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)
        if requests:
            assert finished.wait(1)


def test_owner_input_waits_for_real_delayed_http_ack_without_replay(loopback_gateway):
    endpoint, requests, _ = loopback_gateway
    client = HermesBrowserClient(endpoint, "synthetic-only")
    started = time.monotonic()
    try:
        assert client.browser_session("session-1", "control/input", INPUT) == {
            "outcome": "applied", "sequence": 1}
        assert time.monotonic() - started >= 3.2
        assert requests == [("/v1/browser-sessions/session-1/control/input", INPUT)]
    finally:
        client.close()


def test_status_still_times_out_on_real_delayed_http_reply(loopback_gateway):
    endpoint, requests, _ = loopback_gateway
    client = HermesBrowserClient(endpoint, "synthetic-only")
    try:
        with pytest.raises(HermesGatewayError, match="^runtime_timeout$"):
            client.browser_session("session-1", "status", {})
        assert requests == [("/v1/browser-sessions/session-1/status", {})]
    finally:
        client.close()


def test_lost_http_ack_does_not_automatically_repeat_native_input(loopback_gateway):
    endpoint, requests, settings = loopback_gateway
    settings["disconnect"] = True
    client = HermesBrowserClient(endpoint, "synthetic-only")
    try:
        with pytest.raises(HermesGatewayError, match="^runtime_unavailable$"):
            client.browser_session("session-1", "control/input", INPUT)
        assert requests == [("/v1/browser-sessions/session-1/control/input", INPUT)]
    finally:
        client.close()


@pytest.mark.parametrize("operation", ["open", "control/take", "control/heartbeat",
    "control/input", "control/pause", "control/close", "logins/list", "logins/save", "logins/remove"])
def test_every_owner_operation_uses_launch_fence_metadata_budget(operation):
    requests = []
    def respond(request):
        requests.append(request)
        assert request.extensions["timeout"] == {"connect": 2, "read": 150, "write": 150, "pool": 2}
        return httpx.Response(200, json={"outcome": "applied", "sequence": 1})
    client = HermesBrowserClient("http://127.0.0.1", "synthetic-only", transport=httpx.MockTransport(respond))
    try:
        client.browser_session("session-1", operation, INPUT)
        assert len(requests) == 1
    finally:
        client.close()


@pytest.mark.parametrize("operation", ["status", "frame"])
def test_owner_observer_posts_keep_fast_budget(operation):
    requests = []
    def respond(request):
        requests.append(request)
        assert request.extensions["timeout"] == {"connect": 2, "read": 3, "write": 3, "pool": 2}
        return httpx.Response(200, json={})
    client = HermesBrowserClient("http://127.0.0.1", "synthetic-only", transport=httpx.MockTransport(respond))
    try:
        client.browser_session("session-1", operation, {})
        assert len(requests) == 1
    finally:
        client.close()


@pytest.mark.parametrize("outcome", ["uncertain", "reserved"])
def test_nonfinal_input_ack_is_returned_without_automatic_retry(outcome):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"outcome": outcome, "sequence": 1})
    client = HermesBrowserClient("http://127.0.0.1", "synthetic-only", transport=httpx.MockTransport(respond))
    try:
        assert client.browser_session("session-1", "control/input", INPUT) == {
            "outcome": outcome, "sequence": 1}
        assert len(requests) == 1
    finally:
        client.close()
