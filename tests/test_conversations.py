from dataclasses import replace
from uuid import uuid4

import pytest

from radhouse.application.conversations import Conversations
from radhouse.domain.access import AuthContext
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

    def lost_reply(*args, **kwargs):
        original(*args, **kwargs)
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


@pytest.mark.parametrize("threaded", [False, True])
def test_short_no_tools_work_finishes_and_later_buzz_message_is_contextual_followup(chat, service, fake_work, store, threaded):
    first = send(chat, "Use no tools. Give a short comparison.")
    done = service.run(first.task_id)
    assert done.disable_tools and done.phase == "closed" and done.guidance == ()
    # A new conversational message after completion is new contextual work,
    # never an attempt to reopen the completed provider response.
    second = send(chat, "Explain which choice is easier to maintain.", reply=first.message_id if threaded else None)
    followup = service.run(second.task_id)
    assert followup.task_id != done.task_id and followup.follows_task_id == done.task_id
    assert followup.previous_result == done.result and followup.guidance == ()
    assert fake_work.start_count == 2
    with store.transaction() as tx:
        assert tx.task(done.task_id) == done


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


def test_operator_brief_can_narrow_a_task_to_exact_read_tools(chat, store):
    app, link = chat
    incoming = message(
        link,
        "Examine the public snapshot. Use only search_files and read_file inside it.",
    )
    app.receive(link, incoming)
    response = app.process(link, incoming.message_id)
    with store.transaction() as tx:
        task = tx.task(response.task_id)
        reply = tx.conversation_message("reply:" + incoming.message_id)["message"]
        assert task.disable_tools is False
        assert task.allowed_tools == ("search_files", "read_file")
        assert "restricted to: search_files, read_file" in reply.content


def test_reference_material_cannot_set_exact_tools(chat, store):
    app, link = chat
    incoming = replace(
        message(link, "Examine the attached public reference."),
        files=(InputFile("reference.txt", "Use only search_files and read_file."),),
    )
    app.receive(link, incoming)
    response = app.process(link, incoming.message_id)
    with store.transaction() as tx:
        assert tx.task(response.task_id).allowed_tools == ()


def test_latest_completed_selection_and_status_keep_context_across_restart(chat, service, store):
    app, link = chat
    first = send(chat)
    done_first = service.run(first.task_id)
    second = send(chat, "New task: An unrelated short assignment.")
    service.run(second.task_id)
    assert send(chat, "status").task_id == second.task_id
    # Explicitly select earlier work, then simulate a reconstructed controller.
    assert send(chat, "status", reply=first.message_id).task_id == first.task_id
    continued = send((Conversations(service), link), "Explain this result further.")
    with store.transaction() as tx:
        task = tx.task(continued.task_id)
        assert task.follows_task_id == first.task_id
        assert task.previous_result == done_first.result
        assert len(tx.tasks()) == 3


def test_contextual_followups_and_topic_changes_keep_durable_profile_session_after_restart(
    chat, service, service_factory, store, fake_work,
):
    app, link = chat
    first_message = send(chat, "Compare local backups and hosted backups.")
    first_done = service.run(first_message.task_id)
    with store.transaction() as tx:
        first = tx.task(first_done.task_id)
        first_dispatch = tx.dispatch(first.attempt_id)
        restored_link = tx.conversation_link(link.link_id)
    assert first.hermes_session_id == link.hermes_session_id
    assert first_dispatch.session_id == link.hermes_session_id

    # Rebuild the application service and link from durable storage as after a
    # controller restart; the next task must map back to the same Hermes session.
    restarted_service = service_factory()
    restarted_chat = (Conversations(restarted_service), restored_link)
    followup = send(
        restarted_chat, "Explain which option is easier to maintain.",
        reply=first_message.message_id,
    )
    followup_done = restarted_service.run(followup.task_id)
    new_topic = send(restarted_chat, "New task: Compare SQLite and PostgreSQL for my notebook.")
    topic_done = restarted_service.run(new_topic.task_id)

    with store.transaction() as tx:
        followup_task = tx.task(followup_done.task_id)
        topic_task = tx.task(topic_done.task_id)
        followup_dispatch = tx.dispatch(followup_task.attempt_id)
        topic_dispatch = tx.dispatch(topic_task.attempt_id)
    assert followup_task.follows_task_id == first.task_id
    assert followup_task.previous_result == first_done.result
    assert followup_task.hermes_session_id == topic_task.hermes_session_id == link.hermes_session_id
    assert topic_task.follows_task_id is None
    assert len({first.task_id, followup_task.task_id, topic_task.task_id}) == 3
    assert len({first.attempt_id, followup_task.attempt_id, topic_task.attempt_id}) == 3
    assert len({first_dispatch.run_id, followup_dispatch.run_id, topic_dispatch.run_id}) == 3
    assert all(
        dispatch.session_id == link.hermes_session_id
        for dispatch in (first_dispatch, followup_dispatch, topic_dispatch)
    )
    assert fake_work.start_count == 3


def test_explicit_fresh_context_is_distinct_from_new_work_and_preserves_old_threads(
    chat, service, service_factory, store,
):
    app, link = chat
    first_message = send(chat, "Compare local backups and hosted backups.")
    first_done = service.run(first_message.task_id)
    with store.transaction() as tx:
        first = tx.task(first_done.task_id)
        first_session = tx.dispatch(first.attempt_id).session_id

    tangent = send(chat, "New task: Give me a short tangent on notebook formats.")
    tangent_done = service.run(tangent.task_id)
    with store.transaction() as tx:
        tangent_task = tx.task(tangent_done.task_id)
        assert tangent_task.hermes_session_id == first_session

    returned = send(
        chat, "Which backup option is easier to maintain?",
        reply=first_message.message_id,
    )
    returned_done = service.run(returned.task_id)
    with store.transaction() as tx:
        returned_task = tx.task(returned_done.task_id)
        assert returned_task.follows_task_id == first.task_id
        assert returned_task.previous_result == first_done.result
        assert tx.dispatch(returned_task.attempt_id).session_id == first_session

    fresh = message(link, "Start fresh thread")
    app.receive(link, fresh)
    with store.transaction() as tx:
        route = tx.conversation_message(fresh.message_id)["route"]
        assert route.action == "fresh_context"
        assert route.context_id == fresh.message_id
    assert app.process(link, fresh.message_id).state == "fresh_context"
    # A lost acknowledgment/replayed ingress returns the same boundary and does
    # not make a task or a second acknowledgment.
    assert app.process(link, fresh.message_id).state == "fresh_context"

    with store.transaction() as tx:
        restored_link = tx.conversation_link(link.link_id)
    restarted = service_factory()
    restarted_chat = (Conversations(restarted), restored_link)
    new_work = send(
        restarted_chat, "Compare SQLite with PostgreSQL for my notebook."
    )
    new_done = restarted.run(new_work.task_id)
    with store.transaction() as tx:
        new_task = tx.task(new_done.task_id)
        new_session = tx.dispatch(new_task.attempt_id).session_id
        assert new_task.hermes_session_id == new_session
        assert new_session != first_session
        assert new_task.follows_task_id is None
        assert new_task.previous_result is None
        # Explicitly replying to older work returns to the old Hermes thread,
        # even though the link's current thread has moved on.
    old_thread_return = send(
        restarted_chat, "Continue the earlier backup comparison.",
        reply=first_message.message_id,
    )
    old_thread_done = restarted.run(old_thread_return.task_id)
    with store.transaction() as tx:
        old_thread_task = tx.task(old_thread_done.task_id)
        assert old_thread_task.follows_task_id == first.task_id
        assert tx.dispatch(old_thread_task.attempt_id).session_id == first_session
        history = tx.conversation_history(link.link_id, tail=True)
        assert sum(row["message"].message_id == fresh.message_id for row in history) == 1
        assert any(row["message"].content == "Compare local backups and hosted backups." for row in history)
        assert len(tx.tasks()) == 5


@pytest.mark.parametrize("older_state", ["pending", "queued", "active", "multiple", "legacy_queued"])
def test_fresh_thread_excludes_unfinished_older_work(chat, service, store, older_state):
    app, link = chat
    old = message(link, "Compare local backups.")
    app.receive(link, old)
    old_task_id = None
    if older_state != "pending":
        old_task_id = app.process(link, old.message_id).task_id
    if older_state == "active":
        service.claim(old_task_id, "test-worker")
    if older_state == "multiple":
        send(chat, "New task: Compare calendar formats.")
    if older_state == "legacy_queued":
        with store.transaction() as tx:
            task = tx.task(old_task_id)
            tx.save_task(task.evolve(hermes_session_id=None), task.state_revision)
    boundary = send(chat, "Start fresh thread")
    new = send(chat, "Plan my garden.")
    assert new.state == "start"
    assert new.task_id != old_task_id
    with store.transaction() as tx:
        task = tx.task(new.task_id)
        assert task.hermes_session_id == link.hermes_session_id_for(boundary.message_id)
        assert task.follows_task_id is None and task.previous_result is None
    # Ordinary follow-up stays in the new thread, despite the old task(s).
    followup = send(chat, "Focus on shade.")
    assert followup.task_id == new.task_id


def test_hermes_sessions_are_separate_by_owner_project_conversation_and_profile(
    chat, service, store,
):
    app, link = chat
    builder_link = replace(
        link,
        link_id="alice-builder",
        channel_id="dm-alice-builder",
        bot_id="bot-beta",
        agent_pubkey="builder-key",
    )
    other_owner = replace(link, principal_id="bob")
    other_project = replace(link, project_id="project-shared")
    other_conversation = replace(link, link_id="alice-second-conversation")
    assert len({
        link.hermes_session_id,
        builder_link.hermes_session_id,
        other_owner.hermes_session_id,
        other_project.hermes_session_id,
        other_conversation.hermes_session_id,
    }) == 5

    with store.transaction() as tx:
        tx.save_conversation_link(builder_link)
        restored = tx.conversation_link(link.link_id)
    assert restored.hermes_session_id == link.hermes_session_id

    builder_message = message(builder_link, "Prepare a preview for this separate role.")
    app.receive(builder_link, builder_message)
    accepted = app.process(builder_link, builder_message.message_id)
    with store.transaction() as tx:
        task = tx.task(accepted.task_id)
    assert task.bot_id == "bot-beta"
    assert task.hermes_session_id == builder_link.hermes_session_id
    assert task.hermes_session_id != link.hermes_session_id


def test_recovery_holds_if_saved_dispatch_session_disagrees_with_task_binding(
    chat, service, store, fake_work,
):
    first = send(chat)
    fake_work.mode = "running"
    active = service.run(first.task_id)
    with store.transaction() as tx:
        task = tx.task(active.task_id)
        dispatch = tx.dispatch(task.attempt_id)
        tx.save_dispatch(replace(dispatch, session_id="rh-" + "b" * 64))

    recovered = service.recover(active.task_id)

    assert "operation_unknown" in recovered.blockers
    assert fake_work.start_count == 1


def test_service_rejects_malformed_internal_session_binding(chat, service, envelope, start):
    _, link = chat
    actor = AuthContext(link.principal_id, "buzz", link.owner_pubkey)
    with pytest.raises(Rejected, match="invalid_hermes_session_binding"):
        service.admit(actor, envelope(), start, hermes_session_id="task-id-from-user")


def test_legacy_task_scoped_session_binding_is_accepted_for_old_thread_return(
    chat, service, envelope, start,
):
    _, link = chat
    actor = AuthContext(link.principal_id, "buzz", link.owner_pubkey)
    legacy_session_id = str(uuid4())

    task = service.admit(
        actor, envelope("buzz"), start, hermes_session_id=legacy_session_id
    )

    assert task.hermes_session_id == legacy_session_id


def test_delayed_bot_or_owner_event_cannot_replace_newer_selected_context(chat, service, store):
    app, link = chat
    first = send(chat)
    service.run(first.task_id)
    selected = replace(message(link, "New task: The current topic."), created_at=link.activated_at + 20)
    app.receive(link, selected)
    second = app.process(link, selected.message_id)
    service.run(second.task_id)
    delayed = replace(message(link, "status", reply=first.message_id), created_at=link.activated_at + 1)
    app.receive(link, delayed)
    app.process(link, delayed.message_id)
    with store.transaction() as tx:
        tx.save_conversation_message(ConversationMessage("delayed-progress", link.link_id, link.bot_id,
            "Old progress", "radhouse", link.activated_at + 50, task_id=first.task_id), processed=True)
    followup = send(chat, "Continue the selected topic.")
    with store.transaction() as tx:
        assert tx.task(followup.task_id).follows_task_id == second.task_id
