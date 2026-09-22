from types import SimpleNamespace

import pytest

from radhouse.channels.project_buzz import ProjectBuzzConversationCycle
from radhouse.domain.conversations import ConversationLink


pytestmark = pytest.mark.postgres


class Relay:
    def __init__(self, events=()):
        self.events = list(events)

    def verify_conversation(self, _link):
        return {}

    def messages(self, _link, _since):
        return list(self.events)

    def history_page(self, _link, _since, _before=None):
        return list(self.events), None


def test_unaddressed_project_request_routes_once_to_builder_and_status_is_read_only(
    service, store, clock,
):
    now = int(clock().timestamp())
    channel = "0d84100d-9a9c-45c0-b91f-5be6074519a3"
    owner = "a" * 64
    coordinator = ConversationLink(
        "expenses-coordinator", channel, "personal-alice:alice:buzz", "alice",
        owner, "b" * 64, "bot-alpha", "personal-alice", now,
        member_pubkeys=("b" * 64, "c" * 64, "d" * 64),
        default_agent=True, coordinator=True, channel_kind="stream",
    )
    researcher = ConversationLink(
        "expenses-researcher", channel, "personal-alice:alice:buzz", "alice",
        owner, "c" * 64, "bot-alpha", "personal-alice", now,
        member_pubkeys=coordinator.member_pubkeys, default_agent=False,
        channel_kind="stream",
    )
    builder = ConversationLink(
        "expenses-builder", channel, "personal-alice:alice:buzz", "alice",
        owner, "d" * 64, "bot-beta", "personal-alice", now,
        member_pubkeys=coordinator.member_pubkeys, default_agent=False,
        channel_kind="stream",
    )
    with store.transaction() as tx:
        tx._connection.execute(
            "UPDATE channel_bindings SET subject=%s WHERE subject='alice@buzz'",
            (owner,),
        )
        tx._connection.execute(
            "UPDATE bots SET display_name='Builder',role_name='Builder' "
            "WHERE bot_id='bot-beta'"
        )
        for link in (coordinator, researcher, builder):
            tx.save_conversation_link(link)
    assignment = {
        "id": "1" * 64,
        "pubkey": owner,
        "created_at": now,
        "kind": 9,
        "tags": [["h", channel]],
        "content": "Build the Splitwise CSV import for the Expenses project.",
        "sig": "2" * 128,
    }
    relay = Relay([assignment])
    cycle = ProjectBuzzConversationCycle(
        service,
        SimpleNamespace(link=coordinator, relay=relay),
        (
            SimpleNamespace(link=researcher, relay=Relay()),
            SimpleNamespace(link=builder, relay=Relay()),
        ),
    )

    assert cycle.ingress() == 1
    assert cycle.ingress() == 1
    with store.transaction() as tx:
        tasks = tx.tasks()
        state = tx.project_coordination("personal-alice")
        assert len(tasks) == 1
        assert tasks[0].bot_id == "bot-beta"
        assert state.active_task_id == tasks[0].task_id
        assert state.phase == "building"
        assert tx.conversation_message(assignment["id"])["processed"] is True

    relay.events.append({
        **assignment,
        "id": "3" * 64,
        "created_at": now + 1,
        "content": "status",
    })
    cycle.ingress()
    with store.transaction() as tx:
        assert len(tx.tasks()) == 1
        reply = tx.conversation_message("reply:" + "3" * 64)["message"]
        assert "Project status · building" in reply.content
        assert "Builder is working" in reply.content

    relay.events.append({
        **assignment,
        "id": "4" * 64,
        "created_at": now + 2,
        "tags": [["h", channel], ["mention", "c" * 64, "agent-address"]],
        "content": "@Researcher start a separate investigation",
    })
    cycle.ingress()
    with store.transaction() as tx:
        assert len(tx.tasks()) == 1
        reply = tx.conversation_message("reply:" + "4" * 64)["message"]
        assert "Builder is still working" in reply.content
