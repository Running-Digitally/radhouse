from datetime import datetime, timezone
import os
from uuid import uuid4

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import psycopg
from psycopg.rows import dict_row
import pyotp
import pytest

from radhouse.api.app import create_app
from radhouse.auth.local import LocalAuthService, provision_local_user
from radhouse.domain.tasks import Rejected


pytestmark = pytest.mark.postgres


class UnusedService:
    pass


def test_local_login_requires_password_totp_origin_and_session_csrf(store):
    run_id = os.environ["RADHOUSE_VS0_RUN_ID"]
    principal = f"pilot-{uuid4().hex[:12]}"
    project = f"project-{uuid4().hex[:12]}"
    password = "correct horse battery staple"
    totp_secret = pyotp.random_base32()
    key = Fernet.generate_key().decode("ascii")
    now = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)
    dsn = os.environ["RADHOUSE_VS0_DSN"]
    provision_local_user(
        dsn,
        expected_database=f"radhouse_vs0_{run_id}",
        deployment_id=f"fixture-{run_id}",
        encryption_key=key,
        principal_id=principal,
        username=principal,
        role="admin",
        password=password,
        totp_secret=totp_secret,
        project_id=project,
        project_name="Pilot work",
        bot_id="bot-alpha",
        bot_display_name="Researcher",
        bot_role_name="Researcher",
        provider_binding="fake-local",
        now=now,
    )
    auth = LocalAuthService(
        dsn,
        expected_database=f"radhouse_vs0_{run_id}",
        deployment_id=f"fixture-{run_id}",
        encryption_key=key,
        expected_origin="https://radhouse.test",
        clock=lambda: now,
    )
    app = create_app(UnusedService(), auth.auth_context, local_auth=auth)
    code = pyotp.TOTP(totp_secret).at(now)
    for _ in range(5):
        with pytest.raises(Rejected, match="invalid_credentials"):
            auth.login(principal, "wrong password", code, "brute-source")
    with pytest.raises(Rejected, match="invalid_credentials"):
        auth.login(principal, password, code, "brute-source")
    with TestClient(app, base_url="https://radhouse.test") as client:
        denied = client.post(
            "/auth/login",
            headers={"Origin": "https://radhouse.test"},
            json={"username": principal, "password": "wrong password", "totp_code": code},
        )
        assert denied.status_code == 401
        assert denied.json() == {"code": "invalid_credentials"}
        assert auth.cookie_name not in client.cookies

        login = client.post(
            "/auth/login",
            headers={"Origin": "https://radhouse.test"},
            json={"username": principal, "password": password, "totp_code": code},
        )
        assert login.status_code == 200
        assert "default-src 'self'" in login.headers["content-security-policy"]
        assert login.headers["strict-transport-security"] == "max-age=31536000"
        assert login.json()["principal_id"] == principal
        assert login.json()["project_id"] == project
        cookie = login.headers["set-cookie"].lower()
        assert "httponly" in cookie and "secure" in cookie and "samesite=strict" in cookie

        refreshed = client.get("/auth/session")
        assert refreshed.status_code == 200
        csrf = refreshed.json()["csrf_token"]
        missing_csrf = client.post(
            "/auth/logout", headers={"Origin": "https://radhouse.test"},
        )
        assert missing_csrf.status_code == 403
        logout = client.post(
            "/auth/logout",
            headers={"Origin": "https://radhouse.test", "X-Radhouse-CSRF": csrf},
        )
        assert logout.status_code == 204
        assert client.get("/auth/session").status_code == 401

        replay = client.post(
            "/auth/login",
            headers={"Origin": "https://radhouse.test"},
            json={"username": principal, "password": password, "totp_code": code},
        )
        assert replay.status_code == 401

    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        row = connection.execute(
            "SELECT totp_secret_ciphertext FROM public.local_credentials WHERE principal_id=%s",
            (principal,),
        ).fetchone()
    assert row is not None
    assert totp_secret.encode("ascii") not in bytes(row["totp_secret_ciphertext"])
