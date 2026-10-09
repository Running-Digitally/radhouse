"""Ordered follow-ups preserve exact intent through races and recovery."""
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
from threading import Event

import pytest
from fastapi.testclient import TestClient

from radhouse.chat.app import create_app
from radhouse.chat.service import ChatService
from radhouse.chat.store import ChatStore
from radhouse.chat.attachments import Attachment
from radhouse.domain.tasks import Rejected
from tests.test_minimal_chat import chat, SyntheticAuth


def test_waiting_replay_restart_and_order(chat):
    service, hermes = chat
    keys = [str(uuid4()) for _ in range(3)]
    for i, key in enumerate(keys):
        service.send("alice", key, f"Turn {i}")
    assert len(hermes.requests) == 1
    service.retry("alice", keys[2])
    assert len(hermes.requests) == 1
    reopened = ChatService(ChatStore(service.store.path), hermes.client, owner_id="alice", clock=lambda: 1001)
    hermes.status = "completed"
    reopened.poll("alice")
    assert [body["input"] for _, body in hermes.requests] == ["Turn 0", "Turn 1"]
    reopened.poll("alice")
    assert [body["input"] for _, body in hermes.requests] == ["Turn 0", "Turn 1", "Turn 2"]
    reopened.poll("alice")
    assert all(t["status"] == "completed" for t in reopened.store.history("alice")["turns"])


def test_cancel_waiting_is_idempotent_and_cannot_cancel_active(chat):
    service, hermes = chat
    first, waiting, last = [str(uuid4()) for _ in range(3)]
    for key in (first, waiting, last):
        service.send("alice", key, key)
    with pytest.raises(Rejected, match="message_already_dispatching"):
        service.store.cancel_waiting("alice", first)
    with pytest.raises(Rejected, match="message_not_found"):
        service.store.cancel_waiting("other", waiting)
    service.store.cancel_waiting("alice", waiting)
    service.store.cancel_waiting("alice", waiting)
    hermes.status = "completed"
    service.poll("alice")
    assert [body["input"] for _, body in hermes.requests] == [first, last]


def test_unknown_queued_admission_never_automatically_retries(chat):
    service, hermes = chat
    keys = [str(uuid4()) for _ in range(3)]
    for key in keys:
        service.send("alice", key, key)
    hermes.status = "completed"
    hermes.lose_ack = True
    service.poll("alice")
    for _ in range(3):
        service.poll("alice")
    assert len(hermes.requests) == 2
    assert service.store.find("alice", keys[2])["status"] == "waiting"
    service.retry("alice", keys[1])
    assert hermes.requests[1] == hermes.requests[2]
    assert len(hermes.runs) == 2


def test_restart_after_queue_promotion_before_dispatch_is_safe(chat):
    service, hermes = chat
    first, second = str(uuid4()), str(uuid4())
    service.send("alice", first, "First")
    service.send("alice", second, "Second")
    turn = service.store.pending("alice")
    service.store.observe(turn, "completed", output="Done")
    service.store.promote_waiting(service.store.find("alice", second))
    reopened = ChatService(ChatStore(service.store.path), hermes.client, owner_id="alice", clock=lambda: 1002)
    reopened.poll("alice")
    assert len(hermes.requests) == 2
    assert hermes.requests[1][1]["input"] == "Second"


def test_separate_services_race_with_one_active_run(chat):
    service, hermes = chat
    other = ChatService(ChatStore(service.store.path), hermes.client, owner_id="alice", clock=lambda: 1000)
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(lambda instance: instance.send("alice", str(uuid4()), "Race"), (service, other)))
    assert len(hermes.runs) == 1
    assert [t["status"] for t in service.store.history("alice")["turns"]] == ["queued", "waiting"]


def test_cancel_api_rechecks_owner_origin_and_csrf(chat):
    service, _ = chat
    service.send("alice", str(uuid4()), "First")
    key = str(uuid4()); service.send("alice", key, "Second")
    auth = SyntheticAuth()
    with TestClient(create_app(auth, service), base_url="http://127.0.0.1") as client:
        client.cookies.set(auth.cookie_name, "synthetic-cookie")
        assert client.post(f"/chat/messages/{key}/cancel").status_code == 403
        headers = {"Origin": "http://127.0.0.1", "X-Radhouse-CSRF": "synthetic-csrf"}
        auth.principal = "other"
        assert client.post(f"/chat/messages/{key}/cancel", headers=headers).status_code == 403
        auth.principal = "alice"
        assert client.post(f"/chat/messages/{key}/cancel", headers=headers).status_code == 200


def test_queued_attachments_and_choices_are_immutable(chat):
    service, hermes = chat
    service.send("alice", str(uuid4()), "First")
    key = str(uuid4())
    attachment = Attachment("notes.txt", "text/plain", "text", b"Original reference")
    options = {"terminal_context": {"text": "Frozen excerpt", "source": "selection", "captured_at": "2026-10-09T12:00:00Z"},
        "selection": {"model": "alpha", "thinking": "high"},
        "runtime": {"provider": "configured-lan", "model": "alpha", "model_options": {"reasoning": {"enabled": True, "effort": "high"}}}}
    service.send("alice", key, "Use my reference", (attachment,), request_options=options)
    with pytest.raises(Rejected, match="message_conflict"):
        service.send("alice", key, "Use my reference", (Attachment("notes.txt", "text/plain", "text", b"Changed"),), request_options=options)
    with pytest.raises(Rejected, match="message_options_changed"):
        service.send("alice", key, "Use my reference", (attachment,), request_options={})
    reopened = ChatService(ChatStore(service.store.path), hermes.client, owner_id="alice", clock=lambda:1001)
    hermes.status = "completed";reopened.poll("alice")
    assert "Original reference" in hermes.requests[1][1]["input"]
    assert "Frozen excerpt" in hermes.requests[1][1]["input"]
    assert hermes.requests[1][1]["model"] == "alpha"
    assert hermes.requests[1][1]["model_options"] == options["runtime"]["model_options"]


def test_cancel_racing_with_reservation_never_dispatches_cancelled_turn(chat, monkeypatch):
    service, hermes = chat
    service.send("alice", str(uuid4()), "First")
    key = str(uuid4()); reserve = service.store.reserve
    def cancelling_reserve(*args, **kwargs):
        turn = reserve(*args, **kwargs)
        service.store.cancel_waiting("alice", key)
        return turn
    monkeypatch.setattr(service.store, "reserve", cancelling_reserve)
    result = service.send("alice", key, "Cancelled during admission")
    assert result["turns"][-1]["status"] == "cancelled"
    assert len(hermes.requests) == 1


def test_observer_advances_authorized_queue_without_browser_polling(chat, monkeypatch):
    service, hermes = chat
    service.send("alice", str(uuid4()), "First")
    service.send("alice", str(uuid4()), "Second")
    dispatched = Event();start = service.hermes.start_or_attach
    def observe_dispatch(**kwargs):
        result = start(**kwargs)
        if kwargs["input_text"] == "Second":dispatched.set()
        return result
    monkeypatch.setattr(service.hermes, "start_or_attach", observe_dispatch)
    hermes.status = "completed"
    with TestClient(create_app(SyntheticAuth(), service)):
        assert dispatched.wait(timeout=5)
    assert len(hermes.requests) == 2
