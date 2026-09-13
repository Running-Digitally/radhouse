import base64
import json
from uuid import uuid4

from coincurve import PrivateKey
from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from radhouse.channels.buzz import create_buzz_app
from radhouse.channels.nostr import encoded, sha256, verify_event
from radhouse.config import BuzzConfig
from radhouse.domain.tasks import Rejected
from tests.test_local_reauthentication import local_client

pytestmark = pytest.mark.postgres


def event(key, kind, tags, now, content=""):
    pubkey = key.public_key_xonly.format().hex()
    event_id = sha256(encoded([0, pubkey, now, kind, tags, content]))
    return {"id": event_id, "pubkey": pubkey, "created_at": now, "kind": kind, "tags": tags,
            "content": content, "sig": key.sign_schnorr(bytes.fromhex(event_id)).hex()}


def signed(key, url, method, body, now, extra=()):
    value = event(key, 27235, [["u", url], ["method", method], ["payload", sha256(body)], ["nonce", str(uuid4())], *extra], now)
    return "Nostr " + base64.b64encode(encoded(value)).decode()


@pytest.fixture
def native(service, store, clock, local_client):
    _client, auth, totp, password = local_client
    human, relay = PrivateKey(), PrivateKey()
    pubkey, relaykey = human.public_key_xonly.format().hex(), relay.public_key_xonly.format().hex()
    conversation = "personal-alice:alice:buzz"
    with store.transaction() as tx:
        tx._connection.execute("UPDATE channel_bindings SET subject=%s WHERE channel='buzz' AND principal_id='alice' AND conversation_id=%s", (pubkey, conversation))
    config = BuzzConfig(relay_origin="https://relay.test", relay_pubkey=relaykey,
                        conversations=[{"channel_id": "room-1", "conversation_id": conversation}])
    state = {"member": True, "seen": set(), "role": "member"}
    def relay_read(request):
        assert str(request.url) == "https://relay.test/query"
        assert request.method == "POST"
        assert json.loads(request.content) == [{"kinds": [39002], "authors": [relaykey], "#d": ["room-1"], "limit": 1}]
        authorization = request.headers["authorization"]
        if authorization in state["seen"]:
            return httpx.Response(401)
        state["seen"].add(authorization)
        tags = [["d", "room-1"]] + ([["p", pubkey, "", state["role"]]] if state["member"] else [])
        return httpx.Response(200, json=[event(relay, 39002, tags, int(clock().timestamp()))])
    app = FastAPI()
    app.mount("/buzz", create_buzz_app(service, auth, config, "https://radhouse.test", transport=httpx.MockTransport(relay_read)))
    with TestClient(app, base_url="https://radhouse.test") as client:
        def send(path, body=None, *, csrf="", extra=(), omit_origin=False):
            method = "GET" if body is None else "POST"
            raw = encoded(body) if body is not None else b""
            now = int(clock().timestamp())
            query = encoded([{"kinds": [39002], "authors": [relaykey], "#d": ["room-1"], "limit": 1}])
            membership = signed(human, "https://relay.test/query", "POST", query, now)
            authorization = signed(human, "https://radhouse.test/buzz" + path, method, raw, now,
                [["h", "room-1"], ["relay", "https://relay.test"], ["membership", sha256(membership.encode())], *extra])
            headers = {"Authorization": authorization, "X-Buzz-Membership": membership,
                       "X-Radhouse-CSRF": csrf, "Content-Type": "application/json"}
            if not omit_origin: headers["Origin"] = "https://radhouse.test"
            return client.request(method, "/buzz" + path, content=raw, headers=headers)
        yield send, client, state, totp, password, conversation, human, config, relay_read


def test_native_login_keeps_origin_csrf_and_key_membership_checks(native, clock):
    send, client, state, totp, password, conversation, _key, *_ = native
    login = {"username": "alice", "password": password, "totp_code": totp.at(clock())}
    assert send("/auth/login", login, omit_origin=True).status_code == 403
    response = send("/auth/login", login)
    assert response.status_code == 200, response.text
    assert response.json()["conversation_id"] == conversation
    assert "session_token" not in response.json()
    assert send("/auth/reauthenticate", {"password": password, "totp_code": totp.at(clock())}).status_code == 403
    assert send("/projects").status_code == 200
    state["member"] = False
    assert send("/projects").status_code == 403
    state["member"] = True; state["role"] = "bot"
    assert send("/projects").status_code == 403


def test_native_web_share_one_task_and_publication(native, service, alice, start, envelope, clock):
    send, client, state, totp, password, conversation, key, *_ = native
    response = send("/auth/login", {"username": "alice", "password": password, "totp_code": totp.at(clock())})
    csrf = response.json()["csrf_token"]
    from dataclasses import asdict
    command = asdict(envelope(channel="buzz"))
    command["conversation_id"] = conversation
    body = {"envelope": command, "start": {**asdict(start), "files": []}}
    first = send("/tasks", body, csrf=csrf)
    assert first.status_code == 200, first.text
    again = send("/tasks", body, csrf=csrf)
    assert again.json()["task_id"] == first.json()["task_id"]
    task = service.run(first.json()["task_id"])
    assert service.get(alice, task.task_id, envelope=envelope()).result == task.result
    review = service.prepare_review(alice, task.task_id, task.state_revision, ("alice",), envelope=envelope())
    command = {**command, "command_key": str(uuid4()), "event_id": str(uuid4())}
    publish = {"envelope": command, "expected_revision": review.revision, "content": task.result, "audience": ["alice"]}
    released = send(f"/reviews/{review.review_id}/publish", publish, csrf=csrf)
    assert released.status_code == 200, released.text
    assert send(f"/reviews/{review.review_id}/publish", publish, csrf=csrf).json()["publication_id"] == released.json()["publication_id"]
    assert service.get_publication(alice, task.task_id, envelope=envelope()).publication_id == released.json()["publication_id"]
    replay = client.send(released.request)
    assert replay.status_code == 403  # same signed relay nonce is consumed


def test_signature_rejects_short_keys_changed_body_and_wrong_digest(clock):
    key = PrivateKey()
    valid = event(key, 27235, [], int(clock().timestamp()))
    assert verify_event(valid, 27235) == valid
    for changed in ({"pubkey": "00"}, {"sig": "00"}, {"content": "changed"}, {"id": "0" * 64}):
        with pytest.raises(Rejected): verify_event({**valid, **changed}, 27235)


@pytest.mark.parametrize("revocation", ["key", "session", "project"])
def test_native_rechecks_current_binding_session_and_membership(native, store, clock, revocation):
    send, _, _, totp, password, _, key, *_ = native
    response = send("/auth/login", {"username": "alice", "password": password, "totp_code": totp.at(clock())})
    assert response.status_code == 200
    with store.transaction() as tx:
        if revocation == "key":
            tx._connection.execute("UPDATE channel_bindings SET active=false WHERE channel='buzz' AND subject=%s", (key.public_key_xonly.format().hex(),))
        elif revocation == "session":
            tx._connection.execute("UPDATE local_sessions SET revoked_at=now() WHERE principal_id='alice'")
        else:
            tx._connection.execute("DELETE FROM project_members WHERE principal_id='alice'")
    assert send("/projects").status_code in {401, 403}


def test_native_changed_content_and_wrong_channel_cannot_commit(native, service, alice, start, envelope, clock):
    send, _, _, totp, password, conversation, *_ = native
    login = send("/auth/login", {"username": "alice", "password": password, "totp_code": totp.at(clock())})
    task = service.run(service.admit(alice, envelope(), start).task_id)
    review = service.prepare_review(alice, task.task_id, task.state_revision, ("alice",), envelope=envelope())
    from dataclasses import asdict
    command = asdict(envelope(channel="buzz"))
    command["conversation_id"] = conversation
    body = {"envelope": command, "expected_revision": review.revision, "content": "changed artifact", "audience": ["alice"]}
    assert send(f"/reviews/{review.review_id}/publish", body, csrf=login.json()["csrf_token"]).status_code == 409
    assert send("/projects", extra=[["h", "different-room"]]).status_code == 401
    with service.store.transaction() as tx:
        assert tx.publication(task.task_id) is None
