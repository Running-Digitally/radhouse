"""Admission barriers survive process replacement and fence queued dispatch."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from radhouse.chat.app import create_app
from radhouse.chat.service import ChatService
from radhouse.chat.store import ChatStore
from radhouse.chat.worker_control import DispatchGate
from radhouse.domain.tasks import Rejected
from tests.test_minimal_chat import chat, SyntheticAuth


@pytest.fixture
def gate(tmp_path):
    directory = tmp_path / "operator-control"
    directory.mkdir(mode=0o755)
    (directory / "admission.lock").touch(mode=0o644)
    return DispatchGate(directory)


def test_hold_waits_for_acknowledgement_and_blocks_new_admission(chat, gate, monkeypatch):
    service, hermes = chat
    service.dispatch_gate = gate
    entered, finish, held = Event(), Event(), Event()
    original = hermes.client.start_or_attach
    def delayed(**kwargs):
        entered.set()
        assert finish.wait(5)
        return original(**kwargs)
    monkeypatch.setattr(hermes.client, "start_or_attach", delayed)
    def hold():
        gate.change(str(uuid4()))
        held.set()
    with ThreadPoolExecutor(2) as pool:
        sending = pool.submit(service.send, "alice", str(uuid4()), "First")
        assert entered.wait(5)
        holding = pool.submit(hold)
        assert not held.wait(0.1)
        finish.set()
        sending.result()
        holding.result()
    with pytest.raises(Rejected, match="assistant_maintenance"):
        service.send("alice", str(uuid4()), "Second")
    assert len(hermes.requests) == 1


def test_restart_observes_interruption_but_does_not_advance_queue_until_release(chat, gate):
    service, hermes = chat
    service.dispatch_gate = gate
    first, second, cycle = (str(uuid4()) for _ in range(3))
    service.send("alice", first, "First")
    service.send("alice", second, "Second")
    run_id = service.store.find("alice", first)["run_id"]
    gate.change(cycle)
    restarted = ChatService(ChatStore(service.store.path), hermes.client, owner_id="alice",
                            clock=lambda: 1001, dispatch_gate=DispatchGate(gate.directory))
    hermes.status = "interrupted"
    restarted.poll("alice")
    assert restarted.store.find("alice", first)["status"] == "interrupted"
    assert restarted.store.find("alice", first)["run_id"] == run_id
    assert restarted.store.find("alice", second)["status"] == "waiting"
    with pytest.raises(Rejected, match="assistant_maintenance"):
        restarted.retry("alice", second)
    assert len(hermes.requests) == 1
    gate.change(cycle, release=True)
    restarted.poll("alice")
    assert len(hermes.requests) == 2
    assert hermes.requests[1][1]["input"] == "Second"


def test_hold_identity_cannot_be_released_by_another_cycle(gate):
    cycle = str(uuid4())
    gate.change(cycle)
    gate.change(cycle)  # An interrupted coordinator can safely rejoin its cycle.
    with pytest.raises(ValueError, match="hold_identity_mismatch"):
        gate.change(str(uuid4()), release=True)
    assert gate.held()
    gate.change(cycle, release=True)
    assert not gate.held()


def test_missing_malformed_and_linked_control_fail_closed(gate):
    marker = gate.directory / "hold.json"
    marker.write_text("broken")
    with pytest.raises(Rejected, match="assistant_maintenance"):
        with gate.admission():
            pytest.fail("admission allowed")
    marker.unlink()
    marker.symlink_to(gate.directory / "missing")
    assert gate.held()
    marker.unlink()
    (gate.directory / "admission.lock").unlink()
    assert gate.held()


def test_hold_keeps_read_only_chat_available_and_refuses_mutations(chat, gate):
    service, _ = chat
    service.dispatch_gate = gate
    auth = SyntheticAuth()
    gate.change(str(uuid4()))
    with TestClient(create_app(auth, service), base_url="http://127.0.0.1") as client:
        client.cookies.set(auth.cookie_name, "synthetic-cookie")
        assert client.get("/healthz").status_code == 200
        response = client.post("/chat/messages", json={"request_id": str(uuid4()), "text": "Held"})
        assert response.status_code == 503
        assert response.json() == {"error": "assistant_maintenance"}
        assert response.headers["cache-control"] == "no-store"
