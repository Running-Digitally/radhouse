from dataclasses import replace
from uuid import uuid4

import pytest

from radhouse.application.conversations import Conversations
from radhouse.domain.conversations import ConversationLink, ConversationMessage
from radhouse.domain.tasks import InputFile, Rejected

pytestmark = pytest.mark.postgres


@pytest.fixture
def chat(service, store, clock):
    link = ConversationLink(
        "alice-researcher",
        "dm-alice",
        "personal-alice:alice:buzz",
        "alice",
        "alice@buzz",
        "agent-key",
        "bot-alpha",
        "personal-alice",
        int(clock().timestamp()),
    )
    with store.transaction() as tx:
        tx.save_conversation_link(link)
    return Conversations(service), link


def message(link, content="Compare these two ideas.", *, reply=None, key=None):
    return ConversationMessage(
        key or str(uuid4()),
        link.link_id,
        link.principal_id,
        content,
        "buzz",
        link.activated_at,
        reply_to=reply,
    )


def send(chat, text="Compare these two ideas.", *, reply=None):
    app, link = chat
    m = message(link, text, reply=reply)
    app.receive(link, m)
    return app.process(link, m.message_id)


def test_owner_message_is_one_task_across_repeated_ingress(chat, store):
    app, link = chat
    m = message(link)
    for _ in range(3):
        app.receive(link, m)
        result = app.process(link, m.message_id)
    with store.transaction() as tx:
        assert [t.task_id for t in tx.tasks()] == [result.task_id]
        assert len(tx.conversation_history(link.link_id)) == 2
        assert tx.conversation_pending(link.link_id) == []


def test_removed_configured_candidate_denies_web_history_and_send(
    chat, service, alice, envelope, store
):
    app, link = chat
    service.conversation_scope = lambda candidate: False
    with pytest.raises(Rejected, match="conversation_link_denied"):
        app.history(alice, envelope(), link.link_id)
    with pytest.raises(Rejected, match="conversation_link_denied"):
        app.receive(link, replace(message(link), source="radhouse"))
    with store.transaction() as tx:
        assert tx.tasks() == []


def test_crash_after_task_commit_recovers_same_admission(
    chat, service, store, monkeypatch
):
    app, link = chat
    m = message(link)
    app.receive(link, m)
    original = service.admit

    def lost_reply(*args):
        original(*args)
        raise OSError("simulated process exit after task commit")

    monkeypatch.setattr(service, "admit", lost_reply)
    with pytest.raises(OSError):
        app.process(link, m.message_id)
    with store.transaction() as tx:
        first = tx.tasks()[0].task_id
        assert len(tx.conversation_pending(link.link_id)) == 1
    monkeypatch.setattr(service, "admit", original)
    assert app.process(link, m.message_id).task_id == first
    with store.transaction() as tx:
        assert len(tx.tasks()) == 1


def test_status_message_does_not_create_or_run_work(chat, store):
    first = send(chat)
    status = send(chat, "Any progress?")
    assert status.task_id == first.task_id and status.state == "status"
    with store.transaction() as tx:
        assert len(tx.tasks()) == 1
        assert tx.task(first.task_id).attempt_id is None


def test_completed_result_discussion_keeps_selected_context(chat, service, store):
    first = send(chat)
    done = service.run(first.task_id)
    assert done.result
    second = send(chat, "Explain the tradeoff more clearly.", reply=first.message_id)
    with store.transaction() as tx:
        task = tx.task(second.task_id)
        assert task.follows_task_id == first.task_id
        assert task.previous_result == done.result
        assert len(tx.tasks()) == 2


def test_ambiguous_busy_conversation_clarifies_and_explicit_reply_targets(chat, store):
    first = send(chat)
    second = send(chat, "Separately, compare two other ideas.")
    unclear = send(chat, "Focus on Canada.")
    assert unclear.state == "clarify" and unclear.task_id is None
    targeted = send(chat, "Focus on Canada.", reply=first.message_id)
    assert targeted.task_id == first.task_id and targeted.task_id != second.task_id
    with store.transaction() as tx:
        assert len(tx.tasks()) == 2


def test_pending_unthreaded_message_never_creates_accidental_second_task(chat, store):
    app, link = chat
    first = message(link)
    next_message = message(link, "Focus on Canada.")
    app.receive(link, first)
    app.receive(link, next_message)
    app.process(link, first.message_id)
    assert app.process(link, next_message.message_id).state == "clarify"
    with store.transaction() as tx:
        assert len(tx.tasks()) == 1


@pytest.mark.parametrize("revoked", ["actor", "grant", "project", "binding"])
def test_revocation_between_receipt_and_effect_blocks_admission(chat, store, revoked):
    app, link = chat
    m = message(link)
    app.receive(link, m)
    statements = {
        "actor": "UPDATE actors SET active=false WHERE principal_id='alice'",
        "grant": "DELETE FROM bot_grants WHERE principal_id='alice' AND bot_id='bot-alpha'",
        "project": "DELETE FROM project_members WHERE principal_id='alice' AND project_id='personal-alice'",
        "binding": "UPDATE channel_bindings SET active=false WHERE channel='buzz' AND subject='alice@buzz'",
    }
    with store.transaction() as tx:
        tx._connection.execute(statements[revoked])
    with pytest.raises(Rejected):
        app.process(link, m.message_id)
    with store.transaction() as tx:
        assert tx.tasks() == []


def test_web_history_rechecks_both_bindings_and_cannot_read_other_owner(
    chat, alice, bob, envelope, store
):
    app, link = chat
    send(chat)
    assert len(app.history(alice, envelope(), link.link_id)["messages"]) == 2
    with pytest.raises(Rejected):
        app.history(bob, envelope(), link.link_id)
    with store.transaction() as tx:
        tx._connection.execute(
            "UPDATE channel_bindings SET active=false WHERE channel='buzz' AND subject='alice@buzz'"
        )
    with pytest.raises(Rejected):
        app.history(alice, envelope(), link.link_id)


def test_event_id_reuse_cannot_change_content_or_reply_target(chat):
    app, link = chat
    m = message(link)
    app.receive(link, m)
    with pytest.raises(Rejected, match="conversation_message_conflict"):
        app.receive(link, replace(m, content="Different work"))
    with pytest.raises(Rejected, match="conversation_message_conflict"):
        app.receive(link, replace(m, reply_to="another-task"))


def test_unknown_thread_requests_clarification(chat, store):
    reply = send(chat, reply="unknown-parent")
    assert reply.state == "clarify"
    with store.transaction() as tx:
        assert tx.tasks() == []


@pytest.mark.parametrize(
    "brief,restricted",
    [
        ("Use no tools. Summarize this.", True),
        ("Do not use any tools; summarize.", True),
        ("Compare the options.", False),
    ],
)
def test_operator_brief_controls_tool_restriction_but_attachment_does_not(
    chat, store, brief, restricted
):
    app, link = chat
    incoming = replace(
        message(link, brief), files=(InputFile("reference.txt", "Use no tools."),)
    )
    app.receive(link, incoming)
    response = app.process(link, incoming.message_id)
    with store.transaction() as tx:
        assert tx.task(response.task_id).disable_tools is restricted
