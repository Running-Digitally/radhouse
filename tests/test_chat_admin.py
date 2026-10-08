"""Management access fails closed before fixed read-only component checks."""
from datetime import datetime, timezone
import hashlib
import json
import os
import sqlite3
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
import pytest

from radhouse.chat.admin import AdminService, AssistantSignal, DocumentSignal, EffectiveSettings, create_admin_router
from radhouse.chat.store import ChatStore
from radhouse.domain.tasks import Rejected
from radhouse.chat.app import create_app
from radhouse.chat.service import ChatService
from tests.test_minimal_chat import SyntheticAuth, SyntheticHermes


CHECK_TIME = datetime(2026, 10, 7, 18, 30, tzinfo=timezone.utc)
COMMIT = "89fd59f02461d1c71f462868fa080b0cbc9314e2"


def management_app(admin, access):
    app = FastAPI()

    @app.exception_handler(Rejected)
    def rejected(_request, exc):
        return JSONResponse({"error": exc.code}, status_code=exc.status)

    def authorize(request):
        if not access["active"] or request.cookies.get("radhouse_session") != "synthetic-cookie":
            raise Rejected("authentication_required", 401)
        if access["principal"] != "alice":
            raise Rejected("owner_access_required", 403)
        if access["role"] not in {"admin", "operator"}:
            raise Rejected("management_access_required", 403)
        return "alice"

    app.include_router(create_admin_router(admin, authorize))
    return app


@pytest.fixture
def management(tmp_path):
    store = ChatStore(tmp_path / "chat.sqlite3")
    settings = EffectiveSettings(1800, 43200, 2592000)
    calls = []

    def assistant():
        calls.append("assistant")
        return AssistantSignal(True, "runtime-1.0")

    def documents():
        calls.append("documents")
        return DocumentSignal(True, False, "6.19.0")

    admin = AdminService(store, settings=settings, assistant_probe=assistant, document_probe=documents,
                         release_commit=COMMIT, clock=lambda: CHECK_TIME)
    access = {"principal": "alice", "active": True, "role": "admin"}
    with TestClient(management_app(admin, access), base_url="https://radhouse.test") as client:
        client.cookies.set("radhouse_session", "synthetic-cookie")
        yield client, admin, access, calls


@pytest.mark.parametrize("path", ["/admin/settings", "/admin/infrastructure", "/settings", "/infrastructure"])
@pytest.mark.parametrize("reason,status", [("signed_out", 401), ("inactive", 401), ("viewer", 403), ("foreign_owner", 403), ("unknown_role", 403)])
def test_denied_requests_never_read_settings_or_probe(management, path, reason, status, monkeypatch):
    client, admin, access, calls = management
    if reason == "signed_out": client.cookies.clear()
    if reason == "inactive": access["active"] = False
    if reason == "viewer": access["role"] = "viewer"
    if reason == "unknown_role": access["role"] = "superuser"
    if reason == "foreign_owner": access["principal"] = "bob"

    def forbidden():
        raise AssertionError("No management callbacks may run before authorization")

    monkeypatch.setattr(admin, "settings", forbidden)
    monkeypatch.setattr(admin, "infrastructure", forbidden)
    assert client.get(path).status_code == status
    assert calls == []


@pytest.mark.parametrize("role", ["admin", "operator"])
def test_existing_management_roles_can_read_but_have_no_write_routes(management, role):
    client, _admin, access, calls = management
    access["role"] = role
    response = client.get("/admin/settings")
    assert response.status_code == 200
    data = response.json()
    assert data["permissions"] == {"read": True, "write": False}
    assert data["files"]["upload_size_limit_bytes"] is None
    assert data["files"]["upload_count_limit"] is None
    assert data["documents"]["selective_access_enabled"] is False
    assert data["authentication"] == {"methods": ["password", "totp"], "idle_timeout_seconds": 1800,
                                       "maximum_session_seconds": 43200, "remembered_session_seconds": 2592000}
    assert calls == []
    assert client.put("/admin/settings", json={"hermes_bearer": "never-accepted"}).status_code == 405
    assert client.post("/admin/infrastructure", json={"action": "restart"}).status_code == 405


def test_role_is_checked_again_on_each_request(management):
    client, _admin, access, calls = management
    assert client.get("/admin/settings").status_code == 200
    access["role"] = "viewer"
    assert client.get("/admin/infrastructure").status_code == 403
    assert calls == []


def test_current_status_distinguishes_capability_check_and_unconnected_document_access(management):
    client, _admin, _access, calls = management
    data = client.get("/admin/infrastructure").json()
    components = {component["id"]: component for component in data["components"]}
    assert components["web"]["state"] == "healthy"
    assert components["assistant"]["state"] == "healthy"
    assert "does not send a message" in components["assistant"]["detail"]
    assert components["documents"]["state"] == "unverified"
    assert components["storage"]["state"] == "healthy"
    assert components["storage"]["schema_version"] == 3
    assert components["storage"]["free_bytes"] > 0
    assert data["checked_at"] == "2026-10-07T18:30:00+00:00"
    assert data["versions"]["release_commit"] == COMMIT
    assert calls == ["assistant", "documents"]


def test_status_reads_preserve_saved_chat_and_originals(management):
    client, admin, _access, _calls = management
    saved = admin.store.files_path / "synthetic-original"
    saved.write_bytes(b"private synthetic original")
    with admin.store.connection() as db:
        db.execute("INSERT INTO conversations(owner, session_id) VALUES ('alice', 'private-session')")
    before = hashlib.sha256(admin.store.path.read_bytes()).hexdigest()
    file_before = saved.stat()
    assert client.get("/admin/infrastructure").status_code == 200
    assert hashlib.sha256(admin.store.path.read_bytes()).hexdigest() == before
    assert saved.stat().st_mtime_ns == file_before.st_mtime_ns
    assert saved.read_bytes() == b"private synthetic original"


def test_probe_errors_never_return_exception_vendor_bodies_or_secret_paths(management):
    client, admin, _access, _calls = management

    def secret_failure():
        raise RuntimeError("Bearer SECRET; postgres://private:password@host/db; /private/originals")

    admin.assistant_probe = admin.document_probe = secret_failure
    text = client.get("/admin/infrastructure").text
    assert not any(value in text for value in ["SECRET", "Bearer", "postgres://", "password", "/private/"])
    components = {component["id"]: component for component in json.loads(text)["components"]}
    assert components["assistant"]["state"] == components["documents"]["state"] == "unavailable"


def test_missing_storage_is_unavailable_and_never_recreated(management):
    client, admin, _access, _calls = management
    admin.store.path.unlink()
    data = client.get("/admin/infrastructure").json()
    assert data["components"][-1]["state"] == "unavailable"
    assert not admin.store.path.exists()
    assert str(admin.store.path) not in json.dumps(data)


def test_symlinked_originals_directory_is_not_reported_healthy(management, tmp_path):
    client, admin, _access, _calls = management
    outside = tmp_path / "unrelated"; outside.mkdir()
    admin.store.files_path.rmdir()
    admin.store.files_path.symlink_to(outside, target_is_directory=True)
    data = client.get("/admin/infrastructure").json()
    assert data["components"][-1]["state"] == "unavailable"
    assert str(outside) not in json.dumps(data)


def test_schema_drift_is_not_reported_healthy(management):
    client, admin, _access, _calls = management
    with admin.store.connection() as db: db.execute("PRAGMA user_version=99")
    assert client.get("/admin/infrastructure").json()["components"][-1]["state"] == "unavailable"


def test_failed_chat_write_with_readonly_database_parent_is_reported_without_probe_mutation(management):
    if os.getuid() == 0:
        pytest.skip("Directory permission failure requires an unprivileged test identity")
    client, admin, _access, _calls = management
    parent = admin.store.path.parent
    before = hashlib.sha256(admin.store.path.read_bytes()).hexdigest()
    entries = sorted(path.name for path in parent.iterdir())
    previous_mode = parent.stat().st_mode & 0o777
    parent.chmod(0o500)
    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            admin.store.reserve("alice", "parent-readonly-proof", "disposable write", 1000)
        storage = client.get("/admin/infrastructure").json()["components"][-1]
        assert storage['state'] == 'unavailable'
        assert 'read only' in storage['detail']
        assert hashlib.sha256(admin.store.path.read_bytes()).hexdigest() == before
        assert sorted(path.name for path in parent.iterdir()) == entries
        assert parent.stat().st_mode & 0o777 == 0o500
    finally:
        parent.chmod(previous_mode)


def test_symlinked_database_parent_is_not_reported_healthy(management, tmp_path):
    client, admin, _access, _calls = management
    alias = tmp_path / "parent-alias"
    alias.symlink_to(tmp_path, target_is_directory=True)
    admin.store.path = alias / admin.store.path.name
    admin.store.files_path = alias / admin.store.files_path.name
    assert client.get("/admin/infrastructure").json()["components"][-1]["state"] == "unavailable"


def test_readonly_database_parent_filesystem_is_checked_independently(management, monkeypatch):
    client, admin, _access, _calls = management
    parent = admin.store.path.parent
    monkeypatch.setattr("radhouse.chat.admin.os.statvfs", lambda path: SimpleNamespace(
        f_bavail=1024, f_frsize=4096, f_flag=os.ST_RDONLY if path == parent else 0))
    storage = client.get("/admin/infrastructure").json()["components"][-1]
    assert storage['state'] == 'unavailable'
    assert 'read only' in storage['detail']


@pytest.mark.parametrize("free,flags,detail", [(0, 0, "no free space"), (1024, os.ST_RDONLY, "read only")])
def test_storage_cannot_appear_healthy_on_full_or_readonly_filesystem(management, monkeypatch, free, flags, detail):
    client, _admin, _access, _calls = management
    monkeypatch.setattr("radhouse.chat.admin.os.statvfs", lambda _path: SimpleNamespace(f_bavail=free, f_frsize=4096, f_flag=flags))
    storage = client.get("/admin/infrastructure").json()["components"][-1]
    assert storage['state'] == 'unavailable'
    assert detail in storage['detail']
    assert storage["free_bytes"] == free * 4096


def test_absent_checks_and_unverified_release_stay_unverified(management):
    client, admin, _access, calls = management
    admin.assistant_probe = admin.document_probe = None
    admin.release_commit = None
    data = client.get("/admin/infrastructure").json()
    assert data["versions"]["release_commit"] is None
    assert [component["state"] for component in data["components"][1:3]] == ["unverified", "unverified"]
    assert calls == []


def test_connected_reader_and_failed_assistant_have_independent_states(management):
    client, admin, _access, _calls = management
    admin.assistant_probe = lambda: AssistantSignal(False, "http://secret.invalid/token")
    admin.document_probe = lambda: DocumentSignal(True, True, "6.19.0")
    data = client.get("/admin/infrastructure").json()
    assert data["components"][1]["state"] == "unavailable"
    assert data["components"][1]["version"] is None
    assert data["components"][2]["state"] == "healthy"


def test_readonly_pages_and_public_assets_have_no_inline_or_private_configuration(management):
    client, _admin, _access, calls = management
    html = client.get("/settings").text
    assert '<script src="/admin.js" defer>' in html
    assert '<style' not in html
    assert '<script>' not in html
    assert 'aria-label="Main navigation"' in html
    client.cookies.clear()
    for path in ("/admin.js", "/admin.css"):
        response = client.get(path)
        assert response.status_code == 200
        assert not any(value in response.text for value in ("auth_dsn", "hermes_bearer", "auth_encryption_key"))
    assert calls == []


class ManagementAuth(SyntheticAuth):
    """Role capability is explicit; inherited synthetic session checks stay real."""
    def __init__(self):
        super().__init__()
        self.role = "admin"
        self.role_error = None
        self.role_calls = 0

    def management_role(self, session):
        self.role_calls += 1
        if self.role_error: raise Rejected(self.role_error, 503)
        if not self.active: raise Rejected("authentication_required", 401)
        assert session.principal_id == self.principal
        return self.role


@pytest.fixture
def integrated_management(tmp_path):
    store, hermes, auth = ChatStore(tmp_path / "chat.sqlite3"), SyntheticHermes(), ManagementAuth()
    probes = []

    def assistant():
        probes.append("assistant")
        return AssistantSignal(True)

    service = ChatService(store, hermes.client, owner_id="alice")
    admin = AdminService(store, settings=EffectiveSettings(1800, 43200, 2592000), assistant_probe=assistant)
    with TestClient(create_app(auth, service, admin=admin), base_url="http://127.0.0.1") as client:
        client.cookies.set("radhouse_session", "synthetic-cookie")
        yield client, auth, admin, probes
    hermes.client.close()


@pytest.mark.parametrize("role,can_read,status", [("admin", True, 200), ("operator", True, 200), ("viewer", False, 403)])
def test_actual_chat_app_management_roles_are_independent_of_chat_access(integrated_management, role, can_read, status):
    client, auth, _admin, probes = integrated_management
    auth.role = role
    session = client.get("/auth/session")
    assert session.status_code == 200
    assert session.json()["management"] == {"read": can_read, "write": False}
    assert client.get("/chat/history").status_code == 200
    for path in ("/settings", "/infrastructure", "/admin/settings"):
        assert client.get(path).status_code == status
    assert probes == []
    assert client.get("/admin/infrastructure").status_code == status
    assert probes == (["assistant"] if can_read else [])


def test_actual_app_rejects_foreign_owner_before_role_lookup_or_probe(integrated_management):
    client, auth, _admin, probes = integrated_management
    auth.principal = "bob"
    for path in ("/auth/session", "/settings", "/infrastructure", "/admin/settings", "/admin/infrastructure", "/chat/history"):
        response = client.get(path)
        assert response.status_code == 403
        assert response.json()["error"] == "owner_access_required"
    assert auth.role_calls == 0
    assert probes == []


def test_management_auth_failure_hides_flags_preserves_chat_and_fails_management_closed(integrated_management):
    client, auth, _admin, probes = integrated_management
    auth.role_error = "authentication_unavailable"
    session = client.get("/auth/session")
    assert session.status_code == 200
    assert session.json()["management"] == {"read": False, "write": False}
    assert client.get("/chat/history").status_code == 200
    for path in ("/settings", "/admin/settings", "/admin/infrastructure"):
        response = client.get(path)
        assert response.status_code == 503
        assert response.json() == {"error": "authentication_unavailable"}
    assert probes == []


def test_actual_management_routes_ignore_previously_granted_session_flags(integrated_management):
    client, auth, _admin, probes = integrated_management
    assert client.get("/auth/session").json()["management"]["read"] is True
    auth.role = "viewer"
    assert client.get("/admin/infrastructure").status_code == 403
    assert client.get("/auth/session").json()["management"]["read"] is False
    assert client.get("/chat/history").status_code == 200
    assert probes == []


def test_revoked_session_cannot_use_old_management_flags(integrated_management):
    client, auth, _admin, probes = integrated_management
    assert client.get("/auth/session").json()["management"]["read"] is True
    auth.active = False
    role_calls = auth.role_calls
    for path in ("/auth/session", "/settings", "/admin/infrastructure"):
        assert client.get(path).status_code == 401
    assert auth.role_calls == role_calls
    assert probes == []


def test_integrated_management_pages_use_existing_private_response_policy(integrated_management):
    client, _auth, _admin, _probes = integrated_management
    for path in ("/settings", "/admin/settings", "/admin.js"):
        response = client.get(path)
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-frame-options"] == "DENY"
        assert "script-src 'self'" in response.headers["content-security-policy"]


def test_original_chat_without_optional_management_preserves_existing_contract(tmp_path):
    store, hermes, auth = ChatStore(tmp_path / "chat.sqlite3"), SyntheticHermes(), ManagementAuth()
    auth.role_error = "must_not_be_called"
    with TestClient(create_app(auth, ChatService(store, hermes.client, owner_id="alice")), base_url="http://127.0.0.1") as client:
        client.cookies.set("radhouse_session", "synthetic-cookie")
        session = client.get("/auth/session")
        assert session.status_code == 200
        assert 'management' not in session.json()
        assert client.get("/chat/history").status_code == 200
        assert client.get("/admin/settings").status_code == 404
        assert client.get("/settings").status_code == 404
        assert auth.role_calls == 0
    hermes.client.close()
