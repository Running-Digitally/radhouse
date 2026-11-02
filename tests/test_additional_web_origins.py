"""An additional browser origin keeps the existing login and CSRF boundary."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import os
from types import SimpleNamespace

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pyotp
import pytest
from starlette.requests import Request

from radhouse.auth import local
from radhouse.api.app import create_app
from radhouse.chat import main
from radhouse.chat.browser_transport import _verify_stream_origin
from radhouse.domain.tasks import Rejected


PRIVATE = "https://private.example.test:8443"
PUBLIC = "https://app.example.test"
NOW = datetime(2026, 11, 2, tzinfo=timezone.utc)


def make_auth(**overrides):
    return local.LocalAuthService(
        "host=127.0.0.1 dbname=synthetic user=synthetic",
        expected_database="synthetic", deployment_id="synthetic",
        encryption_key=Fernet.generate_key().decode(), expected_origin=PRIVATE,
        clock=lambda: NOW, **overrides)


def request(origin=None, *, csrf="synthetic-csrf", method="POST"):
    headers = [(b"cookie", b"radhouse_session=synthetic-session")]
    if origin is not None:
        headers.append((b"origin", origin.encode()))
    if csrf is not None:
        headers.append((b"x-radhouse-csrf", csrf.encode()))
    return Request({"type": "http", "method": method, "headers": headers})


@pytest.fixture
def auth():
    return make_auth(additional_origins=[PUBLIC])


@pytest.mark.parametrize("origin", [PRIVATE, PUBLIC, PUBLIC + "/"])
def test_login_origin_accepts_only_configured_addresses(auth, origin):
    auth.verify_origin(request(origin))


@pytest.mark.parametrize("origin", [None, "null", "https://foreign.example.test",
    PUBLIC + ".evil.test", "http://app.example.test", PUBLIC + ":444", PUBLIC + "/login",
    PUBLIC + " " + PRIVATE])
def test_login_origin_rejects_missing_foreign_and_lookalike_values(auth, origin):
    req = request(origin)
    with pytest.raises(Rejected, match="request_origin_denied"):
        auth.verify_origin(req)


def test_omitted_setting_does_not_admit_a_new_hostname():
    auth = make_auth()
    auth.verify_origin(request(PRIVATE))
    req = request(PUBLIC)
    with pytest.raises(Rejected, match="request_origin_denied"):
        auth.verify_origin(req)


@pytest.mark.parametrize("origin", [PRIVATE, PUBLIC])
def test_stream_handshake_uses_configured_origins_even_behind_a_proxy(auth, origin):
    req = request(origin)
    ws = SimpleNamespace(url="ws://untrusted-host.example/stream", headers=req.headers)
    _verify_stream_origin(auth, ws, req)


@pytest.mark.parametrize("origin", [None, "https://foreign.example.test"])
def test_stream_handshake_rejects_missing_or_foreign_origin(auth, origin):
    req = request(origin)
    ws = SimpleNamespace(url="wss://foreign.example.test/stream", headers=req.headers)
    with pytest.raises(Rejected, match="request_origin_denied"):
        _verify_stream_origin(auth, ws, req)


def test_primary_origin_override_remains_compatible_with_local_browser_fixtures(auth):
    auth._expected_origin = "http://127.0.0.1:49152"
    auth.verify_origin(request("http://127.0.0.1:49152"))
    auth.verify_origin(request(PUBLIC))


@pytest.mark.parametrize("value", [None, PUBLIC, {PUBLIC}, {"origin": PUBLIC}, 1])
def test_additional_origins_must_be_an_explicit_sequence(value):
    with pytest.raises(local.LocalAuthError, match="invalid_additional_origins"):
        make_auth(additional_origins=value)


@pytest.mark.parametrize("value", [None, 1, "", "http://example.test", "https://",
    "https://*.example.test", "https://user:password@example.test", PUBLIC + "/path",
    PUBLIC + "?", PUBLIC + "?q=1", PUBLIC + "#", PUBLIC + "#fragment",
    PUBLIC + ":", PUBLIC + ":0", PUBLIC + ":65536", PUBLIC + ":bad",
    "https://[bad]", "https://example.test\\evil", "https://ex%61mple.test",
    " " + PUBLIC, "\x00" + PUBLIC, PUBLIC + "\n"])
def test_additional_origin_rejects_non_origin_configuration(value):
    with pytest.raises(local.LocalAuthError, match="invalid_additional_origin"):
        make_auth(additional_origins=[value])


@pytest.mark.parametrize("value", [PUBLIC, PUBLIC + "/", "https://example.test:8443",
                                   "https://[::1]:8443"])
def test_additional_https_origins_with_explicit_ports(value):
    auth = make_auth(additional_origins=[value])
    auth.verify_origin(request(value.rstrip("/")))


@pytest.fixture
def session_auth(auth, monkeypatch):
    # Keep real origin, cookie, expiry and CSRF checks; replace only database I/O.
    row = {"active": True, "revoked_at": None, "idle_expires_at": NOW + timedelta(minutes=20),
           "absolute_expires_at": NOW + timedelta(hours=12), "remembered": False,
           "csrf_hash": local._digest("synthetic-csrf"),
           "token_hash": local._digest("synthetic-session"), "principal_id": "alice",
           "username": "alice", "assurance_until": NOW + timedelta(minutes=10)}
    calls = []
    def execute(query, _params):
        calls.append(query.split()[0])
        return SimpleNamespace(fetchone=lambda: row)
    @contextmanager
    def connection():
        yield SimpleNamespace(execute=execute)
    monkeypatch.setattr(auth, "_connection", connection)
    monkeypatch.setattr(local, "_verified_connection", lambda *_: None)
    monkeypatch.setattr(auth, "_binding", lambda *_: {
        "conversation_id": "existing-conversation", "binding_revision": 1,
        "project_id": "existing-project"})
    return auth, calls


@pytest.mark.parametrize("origin", [PRIVATE, PUBLIC])
@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_unsafe_session_preserves_owner_and_existing_binding(session_auth, origin, method):
    auth, calls = session_auth
    session = auth.session(request(origin, method=method))
    assert session.principal_id == "alice"
    assert session.conversation_id == "existing-conversation"
    assert session.csrf_token == "synthetic-csrf"
    assert calls == ["SELECT", "UPDATE"]


@pytest.mark.parametrize("origin", [PRIVATE, PUBLIC])
@pytest.mark.parametrize("csrf", [None, "wrong"])
def test_additional_origin_never_bypasses_csrf(session_auth, origin, csrf):
    auth, calls = session_auth
    req = request(origin, csrf=csrf)
    with pytest.raises(Rejected, match="csrf_denied"):
        auth.session(req)
    assert calls == ["SELECT"]


@pytest.mark.parametrize("origin", [None, "https://foreign.example.test"])
def test_valid_cookie_and_csrf_cannot_admit_a_foreign_origin(session_auth, origin):
    auth, calls = session_auth
    req = request(origin)
    with pytest.raises(Rejected, match="request_origin_denied"):
        auth.session(req)
    assert calls == ["SELECT"]


def test_config_loader_and_factory_pass_additional_origins(tmp_path, monkeypatch):
    config = {key: "synthetic" for key in (
        "auth_dsn", "auth_database", "deployment_id", "auth_encryption_key",
        "owner_id", "hermes_endpoint", "hermes_bearer", "transcript_path")}
    config.update(origin=PRIVATE, additional_origins=[PUBLIC])
    path = tmp_path / "chat.json"
    path.write_text(json.dumps(config))
    path.chmod(0o600)
    monkeypatch.setenv("RADHOUSE_CHAT_CONFIG", str(path))
    assert main._load_chat_config()["additional_origins"] == [PUBLIC]
    class StopAfterAuth(Exception):
        """Stop before any factory health checks or network clients."""
    captured = {}
    def capture_auth(_dsn, **kwargs):
        captured.update(kwargs)
        raise StopAfterAuth
    monkeypatch.setattr(main, "LocalAuthService", capture_auth)
    with pytest.raises(StopAfterAuth):
        main.app_factory()
    assert captured["expected_origin"] == PRIVATE
    assert captured["additional_origins"] == [PUBLIC]


@pytest.mark.postgres
@pytest.mark.parametrize("origin", [PRIVATE, PUBLIC])
def test_real_login_and_logout_keep_csrf_and_revocation_at_both_origins(store, origin):
    run_id = os.environ["RADHOUSE_VS0_RUN_ID"]
    dsn = os.environ["RADHOUSE_VS0_DSN"]
    common = {"expected_database": "radhouse_vs0_" + run_id,
              "deployment_id": "fixture-" + run_id,
              "encryption_key": Fernet.generate_key().decode()}
    secret = pyotp.random_base32()
    local.provision_local_user(dsn, **common, principal_id="origin-user",
        username="origin-user", role="admin", password="synthetic password only",
        totp_secret=secret, project_id="origin-project", project_name="Origin test",
        bot_id="bot-alpha", bot_display_name="Fixture", bot_role_name="Fixture",
        provider_binding="fake-local", now=NOW)
    auth = local.LocalAuthService(dsn, **common, expected_origin=PRIVATE,
                                 additional_origins=[PUBLIC], clock=lambda: NOW)
    app = create_app(SimpleNamespace(), auth.auth_context, local_auth=auth)
    with TestClient(app, base_url=origin) as client:
        body = {"username": "origin-user", "password": "synthetic password only",
                "totp_code": pyotp.TOTP(secret).at(NOW)}
        assert client.post("/auth/login", json=body,
                           headers={"Origin": "https://foreign.example.test"}).status_code == 403
        response = client.post("/auth/login", json=body, headers={"Origin": origin})
        assert response.status_code == 200
        csrf = response.json()["csrf_token"]
        assert client.post("/auth/logout", headers={"Origin": origin}).status_code == 403
        assert client.get("/auth/session").status_code == 200
        headers = {"Origin": origin, "X-Radhouse-CSRF": csrf}
        assert client.post("/auth/logout", headers=headers).status_code == 204
        assert client.get("/auth/session").status_code == 401
