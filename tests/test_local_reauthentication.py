from datetime import timedelta
import os

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pyotp
import pytest

from radhouse.api.app import create_app
from radhouse.auth.local import LocalAuthService, provision_local_user

pytestmark = pytest.mark.postgres


@pytest.fixture
def local_client(service, store, clock):
    run_id = os.environ["RADHOUSE_VS0_RUN_ID"]
    dsn = os.environ["RADHOUSE_VS0_DSN"]
    key = Fernet.generate_key().decode()
    secret = pyotp.random_base32()
    password = "synthetic-password-for-tests-only"
    common = dict(expected_database=f"radhouse_vs0_{run_id}", deployment_id=f"fixture-{run_id}", encryption_key=key)
    provision_local_user(dsn, **common, principal_id="alice", username="alice", role="operator",
                         password=password, totp_secret=secret, project_id="personal-alice", project_name="My work",
                         bot_id="bot-alpha", bot_display_name="Researcher", bot_role_name="Researcher",
                         provider_binding="fake-local", now=clock())
    auth = LocalAuthService(dsn, **common, expected_origin="https://radhouse.test", clock=clock)
    with TestClient(create_app(service, auth.auth_context, local_auth=auth), base_url="https://radhouse.test") as client:
        yield client, auth, pyotp.TOTP(secret), password


def login(client, password, code):
    return client.post("/auth/login", headers={"Origin": "https://radhouse.test"},
                       json={"username": "alice", "password": password, "totp_code": code})


def test_multiple_tabs_share_stable_csrf_and_reauthenticate_existing_session(local_client, store, clock):
    client, auth, totp, password = local_client
    response = login(client, password, totp.at(clock()))
    assert response.status_code == 200
    token = client.cookies[auth.cookie_name]
    csrf = response.json()["csrf_token"]
    assert client.get("/auth/session").json()["csrf_token"] == csrf
    assert client.get("/auth/session").json()["csrf_token"] == csrf
    clock.advance(minutes=11)
    headers = {"Origin": "https://radhouse.test", "X-Radhouse-CSRF": csrf}
    body = {"password": password, "totp_code": totp.at(clock())}
    assert client.post("/auth/reauthenticate", json=body).status_code == 403
    refreshed = client.post("/auth/reauthenticate", json=body, headers=headers)
    assert refreshed.status_code == 200
    assert refreshed.json()["assurance_until"] > response.json()["assurance_until"]
    assert client.cookies[auth.cookie_name] == token
    with store.transaction() as tx:
        assert tx._connection.execute("SELECT count(*) AS n FROM local_sessions WHERE principal_id='alice'").fetchone()["n"] == 1
        tx._connection.execute("UPDATE local_sessions SET revoked_at=now() WHERE principal_id='alice'")
    clock.advance(seconds=30)
    assert client.post("/auth/reauthenticate", json={"password": password, "totp_code": totp.at(clock())}, headers=headers).status_code == 401


def test_future_totp_window_cannot_be_replayed_when_clock_advances(local_client, clock):
    client, _auth, totp, password = local_client
    future_code = totp.at(clock() + timedelta(seconds=30))
    assert login(client, password, future_code).status_code == 200
    clock.advance(seconds=30)
    assert login(client, password, future_code).status_code == 401
