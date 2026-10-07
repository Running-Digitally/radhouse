"""Management reads follow live roles and session revocation in the owned DB."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import os
from uuid import uuid4

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import psycopg
import pyotp
import pytest

from radhouse.auth.local import LocalAuthService, provision_local_user
from radhouse.chat.admin import AdminService, EffectiveSettings
from radhouse.chat.app import create_app
from radhouse.chat.service import ChatService
from radhouse.chat.store import ChatStore
from radhouse.domain.tasks import Rejected
from tests.test_minimal_chat import SyntheticHermes


pytestmark = pytest.mark.postgres


@pytest.fixture
def management_identity(store):
    # The existing store fixture verifies exact owned DB and marker first.
    run_id = os.environ["RADHOUSE_VS0_RUN_ID"]
    dsn = os.environ["RADHOUSE_VS0_DSN"]
    principal = "manager-" + uuid4().hex[:12]
    secret = pyotp.random_base32()
    encryption_key = Fernet.generate_key().decode("ascii")
    now = datetime(2026, 10, 7, 15, 0, tzinfo=timezone.utc)
    provision_local_user(dsn, expected_database="radhouse_vs0_" + run_id,
        deployment_id="fixture-" + run_id, encryption_key=encryption_key,
        principal_id=principal, username=principal, role="admin",
        password="synthetic management fixture password", totp_secret=secret,
        project_id="project-" + uuid4().hex[:12], project_name="Management proof",
        bot_id="bot-alpha", bot_display_name="Fixture", bot_role_name="Fixture",
        provider_binding="fake-local", now=now)
    auth = LocalAuthService(dsn, expected_database="radhouse_vs0_" + run_id,
        deployment_id="fixture-" + run_id, encryption_key=encryption_key,
        expected_origin="http://127.0.0.1", secure_cookie=False, clock=lambda: now)
    session = auth.login(principal, "synthetic management fixture password",
        pyotp.TOTP(secret).at(now), "127.0.0.1", remember_browser=False)
    return auth, session, dsn, now


def test_management_role_uses_current_role_and_session_identity(management_identity):
    auth, session, dsn, now = management_identity
    assert auth.management_role(session) == "admin"
    with psycopg.connect(dsn) as db:
        db.execute("UPDATE actors SET role='operator' WHERE principal_id=%s", (session.principal_id,))
    assert auth.management_role(session) == "operator"
    with psycopg.connect(dsn) as db:
        db.execute("UPDATE actors SET role='viewer' WHERE principal_id=%s", (session.principal_id,))
    assert auth.management_role(session) == "viewer"
    with pytest.raises(Rejected, match="authentication_required"):
        auth.management_role(replace(session, principal_id="unrelated-principal"))
    with psycopg.connect(dsn) as db:
        db.execute("UPDATE local_sessions SET absolute_expires_at=%s WHERE principal_id=%s",
                   (now, session.principal_id))
    with pytest.raises(Rejected, match="authentication_required"):
        auth.management_role(session)


def test_management_pages_reauthorize_after_role_change_and_revocation(management_identity, tmp_path):
    auth, session, dsn, now = management_identity
    hermes = SyntheticHermes()
    service = ChatService(ChatStore(tmp_path / "chat.sqlite3"), hermes.client, owner_id=session.principal_id)
    admin = AdminService(service.store, settings=EffectiveSettings(**auth.session_limits()))
    try:
        with TestClient(create_app(auth, service, admin=admin), base_url="http://127.0.0.1") as client:
            client.cookies.set(auth.cookie_name, session.token)
            assert client.get("/auth/session").json()["management"] == {"read": True, "write": False}
            assert client.get("/admin/settings").status_code == 200
            with psycopg.connect(dsn) as db:
                db.execute("UPDATE actors SET role='viewer' WHERE principal_id=%s", (session.principal_id,))
            assert client.get("/admin/infrastructure").status_code == 403
            assert client.get("/auth/session").json()["management"]["read"] is False
            assert client.get("/chat/history").status_code == 200
            with psycopg.connect(dsn) as db:
                db.execute("UPDATE local_sessions SET revoked_at=%s WHERE principal_id=%s", (now, session.principal_id))
            assert client.get("/settings").status_code == 401
            assert client.get("/admin/infrastructure").status_code == 401
    finally:
        hermes.client.close()
