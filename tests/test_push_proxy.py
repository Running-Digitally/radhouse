"""A real CONNECT listener proves both clients use only the explicit proxy."""
from contextlib import contextmanager
import socketserver
from threading import Thread
from types import SimpleNamespace
from uuid import uuid4

import pytest
from google.auth.exceptions import TransportError

from radhouse.chat.push import notification
from radhouse.chat.push_credentials import GooglePushToken, TOKEN_URI
from radhouse.chat.push_fcm import FCMSender
from radhouse.chat.push_proxy import push_proxy
from radhouse.chat.main import _configure_push
from tests.test_push_credentials import credential_file


@contextmanager
def refusing_proxy():
    requests = []

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            self.connection.settimeout(3)
            lines = []
            while True:
                line = self.rfile.readline(8192)
                if line in (b"\r\n", b"\n", b""):
                    break
                lines.append(line)
            requests.append(b"".join(lines))
            self.wfile.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")

    with socketserver.TCPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_address[1]}", requests
        finally:
            server.shutdown()
            thread.join(timeout=5)


@pytest.mark.parametrize("url", ["https://127.0.0.1:8080", "http://localhost:8080",
    "http://192.0.2.1:8080", "http://user:secret@127.0.0.1:8080", "http://127.0.0.1:8080/",
    "http://127.0.0.1:8080?x=1", "http://127.0.0.1:443", "http://127.0.0.1:65536", 123])
def test_proxy_refuses_remote_ambiguous_and_credential_urls(url):
    with pytest.raises(ValueError, match="invalid_push_proxy"):
        push_proxy(url)


def test_fcm_connects_only_to_explicit_proxy_without_leaking_bearer(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    with refusing_proxy() as (proxy, requests):
        sender = FCMSender("synthetic-project", lambda: "synthetic-oauth-secret", proxy_url=proxy)
        try:
            result = sender("synthetic-registration-token-0001", "ios", notification("owner", str(uuid4())))
        finally:
            sender.close()
    assert result.outcome == "retry"
    assert len(requests) == 1
    assert requests[0].startswith(b"CONNECT fcm.googleapis.com:443 HTTP/")
    assert b"synthetic-oauth-secret" not in requests[0]
    assert b"synthetic-registration-token" not in requests[0]


def test_oauth_connects_only_to_explicit_proxy_without_leaking_assertion(tmp_path, monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    credential = SimpleNamespace(valid=False)

    def refresh(request):
        request(TOKEN_URI, method="POST", body=b"synthetic-private-assertion")

    credential.refresh = refresh
    monkeypatch.setattr("radhouse.chat.push_credentials.service_account.Credentials.from_service_account_info",
                        lambda *_args, **_kwargs: credential)
    path = credential_file(tmp_path)
    with refusing_proxy() as (proxy, requests):
        token = GooglePushToken(path, "synthetic-project", proxy_url=proxy)
        try:
            with pytest.raises(TransportError):
                token()
        finally:
            token.close()
    assert len(requests) == 1
    assert requests[0].startswith(b"CONNECT oauth2.googleapis.com:443 HTTP/")
    assert b"synthetic-private-assertion" not in requests[0]


def test_proxy_is_optional():
    assert push_proxy(None) is None


def test_factory_rejects_remote_proxy_before_creating_outbox(tmp_path):
    database = tmp_path / "outbox.sqlite3"
    config = {"push": {"project_id": "synthetic-project", "credentials_path": "/missing",
                      "database_path": str(database), "encryption_key": "synthetic",
                      "proxy_url": "http://192.0.2.1:8080"}}
    with pytest.raises(ValueError, match="invalid_push_proxy"):
        _configure_push(config, None, None, None)
    assert not database.exists()
