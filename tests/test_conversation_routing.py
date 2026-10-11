from types import SimpleNamespace

from radhouse.application.conversations import Conversations
from radhouse.domain.conversations import ConversationLink, ConversationMessage


class RoutingStore:
    def __init__(self, link, *, context_id=None, context_created_at=1, reply=None, target=None, dispatch=None):
        self.link = link
        self.context_id = context_id
        self.context_created_at = context_created_at
        self.reply = reply
        self.target = target
        self.saved_dispatch = dispatch

    def conversation_context_id(self, _link_id, *, at_or_before=None):
        if at_or_before is not None and self.context_created_at > at_or_before:
            return None
        return self.context_id

    def conversation_pending(self, _link_id, limit=20):
        return []

    def conversation_reply(self, _link_id, _message_id):
        return self.reply

    def conversation_reply_in_channel(self, _channel_id, _message_id):
        return None

    def conversation_link(self, _link_id):
        return self.link

    def task(self, _task_id):
        return self.target

    def dispatch(self, _attempt_id):
        return self.saved_dispatch

    def conversation_task_messages(self, _link_id):
        return []

    def conversation_focus(self, _link, *, hermes_session_id=None):
        return None


def sample_link():
    return ConversationLink(
        "alice-researcher", "dm-alice", "personal-alice:alice:buzz", "alice",
        "alice@buzz", "agent-key", "bot-alpha", "personal-alice", 1,
    )


def sample_message(link, content, *, reply_to=None, addressed=False, created_at=1):
    return ConversationMessage(
        "message-01", link.link_id, link.principal_id, content, "buzz", created_at,
        reply_to=reply_to, addressed=addressed,
    )


def test_fresh_action_creates_boundary_without_creating_work():
    link = sample_link()
    app = Conversations(None)
    message = sample_message(link, "Start fresh thread")

    route = app._route(RoutingStore(link), link, message)

    assert route.action == "fresh_context"
    assert route.context_id == message.message_id
    assert route.task_id is None
    assert route.hermes_session_id is None


def test_new_work_item_keeps_current_context():
    link = sample_link()
    app = Conversations(None)
    route = app._route(
        RoutingStore(link, context_id="fresh-boundary"),
        link,
        sample_message(link, "New task: Compare SQLite and PostgreSQL."),
    )

    assert route.action == "start"
    assert route.hermes_session_id == link.hermes_session_id_for("fresh-boundary")


def test_delayed_pre_boundary_message_does_not_move_into_newer_thread():
    link = sample_link()
    route = Conversations(None)._route(
        RoutingStore(link, context_id="future-boundary", context_created_at=20),
        link,
        sample_message(link, "New task: A delayed earlier event.", created_at=10),
    )

    assert route.hermes_session_id == link.hermes_session_id


def test_reply_to_older_task_returns_to_its_saved_thread_after_fresh_boundary():
    link = sample_link()
    old_session = link.hermes_session_id
    target = SimpleNamespace(
        task_id="older-task", bot_id=link.bot_id, phase="closed", result="saved result",
        hermes_session_id=old_session,
    )
    reply = {
        "message": SimpleNamespace(link_id=link.link_id, task_id=target.task_id),
    }
    app = Conversations(None)
    route = app._route(
        RoutingStore(link, context_id="fresh-boundary", reply=reply, target=target),
        link,
        sample_message(link, "Explain the earlier result.", reply_to="older-result"),
    )

    assert route.action == "start"
    assert route.follows_task_id == target.task_id
    assert route.hermes_session_id == old_session


def test_reply_to_legacy_task_reuses_its_saved_task_scoped_session():
    link = sample_link()
    legacy_session = "4d4c63eb-7eed-46c9-8cde-cc96f14c0a88"
    target = SimpleNamespace(
        task_id="older-task", bot_id=link.bot_id, phase="closed", result="saved result",
        hermes_session_id=None, attempt_id="attempt-01",
    )
    reply = {
        "message": SimpleNamespace(link_id=link.link_id, task_id=target.task_id),
    }
    dispatch = SimpleNamespace(session_id=legacy_session)
    route = Conversations(None)._route(
        RoutingStore(link, context_id="fresh-boundary", reply=reply, target=target, dispatch=dispatch),
        link,
        sample_message(link, "Continue the older work.", reply_to="older-result"),
    )

    assert route.hermes_session_id == legacy_session
