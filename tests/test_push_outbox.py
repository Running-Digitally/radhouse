from dataclasses import replace
import hashlib
import sqlite3
from uuid import uuid4

from cryptography.fernet import Fernet
import pytest

from radhouse.chat.push import PushBinding, PushOutbox, PushResult, notification
from radhouse.chat.store import ChatStore
from radhouse.domain.tasks import Rejected


@pytest.fixture
def push(tmp_path):
    now = [1_800_000_000.0]
    key = Fernet.generate_key().decode()
    outbox = PushOutbox(tmp_path / "push.sqlite", key, clock=lambda: now[0])
    chat = ChatStore(tmp_path / "chat.sqlite")
    binding = PushBinding("synthetic-owner", "synthetic-conversation", 1,
                          hashlib.sha256(b"synthetic-session").hexdigest(), now[0] + 7200)
    return outbox, chat, binding, now, key


def turn(chat, owner, now, status="completed"):
    saved = chat.reserve(owner, str(uuid4()), "Private synthetic message", now)
    with chat.connection() as db:
        db.execute("UPDATE turns SET status=?,output=? WHERE seq=?", (status, "Private reply", saved["seq"]))
    return saved


def rows(outbox, table="deliveries"):
    assert table in {"devices", "deliveries"}
    with outbox.connection() as db:
        return [dict(row) for row in db.execute("SELECT * FROM " + table)]


def register(outbox, binding, latest=0, token="synthetic-fcm-token-00001", installation=None):
    identifier = installation or str(uuid4())
    outbox.register(identifier, binding, "ios", token, latest_seq=latest)
    return identifier


def test_completion_reconciliation_survives_restart_and_never_replays_history(push):
    outbox, chat, binding, now, key = push
    old = turn(chat, binding.principal_id, now[0])
    register(outbox, binding, old["seq"])
    first = turn(chat, binding.principal_id, now[0], "running")
    second = turn(chat, binding.principal_id, now[0])
    outbox.reconcile(chat, binding.principal_id)
    assert [r["request_id"] for r in rows(outbox)] == [second["request_id"]]
    with chat.connection() as db:
        db.execute("UPDATE turns SET status='completed' WHERE seq=?", (first["seq"],))
    restarted = PushOutbox(outbox.path, key, clock=lambda: now[0])
    restarted.reconcile(chat, binding.principal_id)
    restarted.reconcile(chat, binding.principal_id)
    assert {r["request_id"] for r in rows(outbox)} == {first["request_id"], second["request_id"]}


def test_tokens_encrypted_and_payload_has_no_private_content(push):
    outbox, chat, binding, now, _ = push
    register(outbox, binding)
    saved = turn(chat, binding.principal_id, now[0])
    outbox.reconcile(chat, binding.principal_id)
    sent = []
    checked = []
    def authorize(value):
        checked.append(value)
        return True
    def send(token, platform, payload):
        sent.append((token, platform, payload))
        return PushResult("sent")
    assert outbox.dispatch_one(authorize, send)
    assert not outbox.dispatch_one(authorize, send)
    assert checked == [binding]
    assert sent == [("synthetic-fcm-token-00001", "ios", notification(binding.principal_id, saved["request_id"]))]
    assert set(sent[0][2]) == {"version", "kind", "event_id", "request_id"}
    disk = outbox.path.read_bytes()
    assert b"synthetic-fcm-token-00001" not in disk
    assert b"Private reply" not in disk
    assert b"synthetic-session" not in disk


def test_rotation_retargets_pending_without_replaying_sent_events(push):
    outbox, chat, binding, now, _ = push
    identifier = register(outbox, binding)
    first = turn(chat, binding.principal_id, now[0])
    outbox.reconcile(chat, binding.principal_id)
    outbox.dispatch_one(lambda _: True, lambda *_: PushResult("sent"))
    second = turn(chat, binding.principal_id, now[0])
    outbox.reconcile(chat, binding.principal_id)
    register(outbox, binding, token="synthetic-rotated-token-0002", installation=identifier)
    outbox.reconcile(chat, binding.principal_id)
    sent = []
    def send(token, _platform, payload):
        sent.append((token, payload["request_id"]))
        return PushResult("sent")
    outbox.dispatch_one(lambda _: True, send)
    assert sent == [("synthetic-rotated-token-0002", second["request_id"])]
    assert first["request_id"] != second["request_id"]


@pytest.mark.parametrize("reason", ["invalid", "revoked", "expired", "unregister", "new-session"])
def test_no_delivery_after_revocation_expiry_or_session_change(push, reason):
    outbox, chat, binding, now, _ = push
    identifier = register(outbox, binding)
    saved = turn(chat, binding.principal_id, now[0])
    outbox.reconcile(chat, binding.principal_id)
    calls = []
    if reason == "expired":
        now[0] += 7201
    elif reason == "unregister":
        outbox.unregister(identifier, binding.principal_id, binding.session_hash)
        outbox.unregister(identifier, binding.principal_id, binding.session_hash)
    elif reason == "new-session":
        new = replace(binding, session_hash=hashlib.sha256(b"new-session").hexdigest())
        register(outbox, new, saved["seq"], installation=identifier)
        outbox.reconcile(chat, binding.principal_id)
    def send(*args):
        calls.append(args)
        return PushResult("invalid")
    outbox.dispatch_one(lambda _: reason != "revoked", send)
    assert len(calls) == (1 if reason == "invalid" else 0)
    assert not outbox.dispatch_one(lambda _: True, send)


def test_transient_failure_uses_bounded_retry_and_stable_event(push):
    outbox, chat, binding, now, _ = push
    register(outbox, binding)
    turn(chat, binding.principal_id, now[0])
    outbox.reconcile(chat, binding.principal_id)
    events = []
    def send(_token, _platform, payload):
        events.append(payload["event_id"])
        return PushResult("retry")
    for _ in range(5):
        assert outbox.dispatch_one(lambda _: True, send)
        assert not outbox.dispatch_one(lambda _: True, send)
        now[0] = rows(outbox)[0]["due_at"]
    assert rows(outbox)[0]["state"] == "exhausted"
    assert len(set(events)) == 1


def test_old_session_cleanup_cannot_remove_new_session_registration(push):
    outbox, _, binding, _, _ = push
    identifier = register(outbox, binding)
    newer = replace(binding, session_hash=hashlib.sha256(b"newer-session").hexdigest())
    register(outbox, newer, installation=identifier)
    outbox.unregister(identifier, binding.principal_id, binding.session_hash)
    assert rows(outbox, "devices")[0]["session_hash"] == newer.session_hash
    outbox.unregister(identifier, newer.principal_id, newer.session_hash)
    assert rows(outbox, "devices") == []


def test_expired_devices_do_not_consume_live_registration_quota(push):
    outbox, _, binding, now, _ = push
    expired = []
    for number in range(16):
        expired.append(register(outbox, binding, token=f"synthetic-old-token-{number:04}"))
    now[0] = binding.expires_at + 1
    current = replace(binding, expires_at=now[0] + 7200)
    for number in range(16):
        register(outbox, current, token=f"synthetic-new-token-{number:04}")
    with pytest.raises(Rejected, match="push_device_limit"):
        register(outbox, current, installation=expired[0], token="synthetic-old-token-0000")


def test_auth_outage_never_sends_and_retains_retry(push):
    outbox, chat, binding, now, _ = push
    register(outbox, binding)
    turn(chat, binding.principal_id, now[0])
    outbox.reconcile(chat, binding.principal_id)
    def unavailable(_):
        raise RuntimeError("private provider failure")
    def unexpected(*_):
        pytest.fail("Must not send when current authorization is unknown")
    outbox.dispatch_one(unavailable, unexpected)
    assert rows(outbox)[0]["state"] == "pending"
    assert rows(outbox)[0]["attempts"] == 1


def test_owner_and_token_conflicts_and_registration_limits(push):
    outbox, _, binding, _, _ = push
    identifier = register(outbox, binding)
    other = replace(binding, principal_id="foreign-owner")
    with pytest.raises(Rejected, match="push_installation_conflict"):
        register(outbox, other, installation=identifier)
    with pytest.raises(Rejected, match="push_token_conflict"):
        register(outbox, binding)
    outbox.unregister(identifier, other.principal_id, other.session_hash)
    assert len(rows(outbox, "devices")) == 1
    for number in range(15):
        register(outbox, binding, token=f"synthetic-distinct-token-{number:04}")
    with pytest.raises(Rejected, match="push_device_limit"):
        register(outbox, binding, token="synthetic-over-limit-token")


@pytest.mark.parametrize("identifier,platform,token", [
    ("bad", "ios", "synthetic-long-token-0001"),
    (str(uuid4()), "web", "synthetic-long-token-0001"),
    (str(uuid4()), "ios", "token\r\nheader"),
    (str(uuid4()), "ios", "x" * 4097),
])
def test_registration_validation(push, identifier, platform, token):
    outbox, _, binding, _, _ = push
    with pytest.raises(Rejected):
        outbox.register(identifier, binding, platform, token, latest_seq=0)


def test_storage_refuses_shared_file_symlink_and_foreign_schema(tmp_path):
    key = Fernet.generate_key().decode()
    path = tmp_path / "bad.sqlite"
    path.write_bytes(b"")
    path.chmod(0o644)
    with pytest.raises(ValueError, match="private_regular"):
        PushOutbox(path, key)
    path.chmod(0o600)
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises(ValueError, match="private_regular"):
        PushOutbox(link, key)
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE foreign_data (value TEXT)")
    with pytest.raises(ValueError, match="schema_mismatch"):
        PushOutbox(path, key)


def test_reconciliation_batches_without_losing_later_completions_and_expires_storage(push):
    outbox, chat, binding, now, _ = push
    register(outbox, binding)
    for _ in range(270):
        turn(chat, binding.principal_id, now[0])
    outbox.reconcile(chat, binding.principal_id)
    assert len(rows(outbox)) == 270
    now[0] += 31 * 86400
    outbox.reconcile(chat, binding.principal_id)
    assert rows(outbox) == []
    assert rows(outbox, "devices") == []


def test_rotation_serializes_with_inflight_delivery_across_connections(push):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    outbox, chat, binding, now, key = push
    identifier = register(outbox, binding)
    turn(chat, binding.principal_id, now[0])
    outbox.reconcile(chat, binding.principal_id)
    second = PushOutbox(outbox.path, key, clock=lambda: now[0])
    entered, release, attempted = Event(), Event(), Event()
    def send(*_):
        entered.set()
        assert release.wait(timeout=3)
        return PushResult("sent")
    def rotate():
        attempted.set()
        register(second, binding, token="rotated-synthetic-token-002", installation=identifier)
    with ThreadPoolExecutor(max_workers=2) as pool:
        sending = pool.submit(outbox.dispatch_one, lambda _: True, send)
        assert entered.wait(timeout=3)
        rotating = pool.submit(rotate)
        try:
            assert attempted.wait(timeout=3)
            assert not rotating.done()
        finally:
            release.set()
        sending.result(timeout=3)
        rotating.result(timeout=3)
    assert rows(outbox)[0]["state"] == "sent"
    assert rows(outbox, "devices")[0]["generation"] == 2
