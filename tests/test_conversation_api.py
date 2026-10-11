from dataclasses import asdict

from fastapi.testclient import TestClient
import pytest

from radhouse.api.app import create_app
from tests.test_conversations import chat

pytestmark = pytest.mark.postgres


def test_web_conversation_send_retry_history_and_binding(
    chat, service, alice, bob, envelope, store
):
    _, link = chat
    identity = [alice]
    with TestClient(create_app(service, lambda request: identity[0])) as client:
        env = asdict(envelope())
        query = {"conversation_id": env["conversation_id"], "binding_revision": 1}
        response = client.get("/conversations", params=query)
        assert response.status_code == 200, response.text
        assert response.json()[0]["link_id"] == link.link_id
        path = f"/conversations/{link.link_id}/messages"
        body = {
            "envelope": env,
            "content": "Summarize this reference.",
            "files": [{"name": "notes.txt", "content": "A useful reference."}],
        }
        first = client.post(path, json=body)
        assert first.status_code == 200, first.text
        assert client.post(path, json=body).json() == first.json()
        with store.transaction() as tx:
            tasks = tx.tasks()
            assert len(tasks) == 1
            assert tasks[0].files[0].content == "A useful reference."
        history = client.get(path, params=query)
        assert (
            history.status_code == 200
            and history.headers["cache-control"] == "no-store"
        )
        assert len(history.json()["messages"]) == 2
        cursor = history.json()["cursor"]
        assert (
            client.get(path, params={**query, "after": cursor}).json()["messages"] == []
        )
        assert client.post(path, json={**body, "files": []}).status_code == 409
        identity[0] = bob
        denied = client.get(path, params=query)
        assert (
            denied.status_code == 403 and denied.headers["cache-control"] == "no-store"
        )


def test_conversation_message_rejects_spoofed_authority(chat, service, alice, envelope):
    _, link = chat
    with TestClient(create_app(service, lambda request: alice)) as client:
        body = {
            "envelope": asdict(envelope()),
            "content": "Work",
            "principal_id": "bob",
        }
        response = client.post(f"/conversations/{link.link_id}/messages", json=body)
        assert response.status_code == 422
        assert response.json() == {"code": "invalid_request"}


def test_start_fresh_thread_is_an_idempotent_conversation_action(
    chat, service, alice, envelope, store
):
    _, link = chat
    with TestClient(create_app(service, lambda request: alice)) as client:
        env = asdict(envelope())
        path = f"/conversations/{link.link_id}/messages"
        body = {"envelope": env, "content": "Start fresh thread", "files": []}
        first = client.post(path, json=body)
        retry = client.post(path, json=body)
        assert first.status_code == retry.status_code == 200
        assert first.json() == retry.json()
        assert first.json()["state"] == "fresh_context"
        with store.transaction() as tx:
            assert tx.tasks() == []
            rows = tx.conversation_history(link.link_id)
            assert len(rows) == 2
            assert rows[0]["message"].state == "fresh_context"
            assert rows[1]["message"].content.startswith("Started a fresh agent thread")
