from coincurve import PrivateKey
import pytest

from radhouse.application.conversations import Conversations
from radhouse.channels.buzz_conversations import BuzzConversationCycle
from radhouse.domain.conversations import ConversationLink, ConversationMessage
from tests.test_buzz_relay import signed


pytestmark = pytest.mark.postgres


@pytest.fixture
def project_chat(service, store, clock):
    owner, researcher, builder = PrivateKey(), PrivateKey(), PrivateKey()
    key = lambda value: value.public_key_xonly.format().hex()
    channel = "76d35b0c-0710-4aa2-83f2-11bd925913b2"
    members = tuple(sorted((key(researcher), key(builder))))
    common = dict(
        channel_id=channel,
        conversation_id="personal-alice:alice:buzz",
        principal_id="alice",
        owner_pubkey=key(owner),
        project_id="personal-alice",
        activated_at=int(clock().timestamp()),
        member_pubkeys=members,
    )
    research_link = ConversationLink(
        link_id="project-researcher",
        agent_pubkey=key(researcher),
        bot_id="bot-alpha",
        default_agent=True,
        **common,
    )
    builder_link = ConversationLink(
        link_id="project-builder",
        agent_pubkey=key(builder),
        bot_id="bot-beta",
        default_agent=False,
        **common,
    )
    with store.transaction() as tx:
        tx._connection.execute(
            "UPDATE channel_bindings SET subject=%s WHERE subject='alice@buzz'",
            (key(owner),),
        )
        tx.save_conversation_link(research_link)
        tx.save_conversation_link(builder_link)
    return (
        BuzzConversationCycle(service, None, research_link),
        BuzzConversationCycle(service, None, builder_link),
        owner,
    )


def event(cycle, owner, content, *, tags=(), offset=0):
    return signed(
        owner,
        9,
        [["h", cycle.link.channel_id], *tags],
        content,
        cycle.link.activated_at + offset,
    )


def test_standard_mentions_and_replies_select_one_project_agent(project_chat, store):
    researcher, builder, owner = project_chat
    ordinary = event(researcher, owner, "Compare the options.")
    addressed = event(
        researcher,
        owner,
        "@Beacon turn the recommendation into a prototype.",
        tags=[["mention", builder.link.agent_pubkey]],
        offset=1,
    )
    ambiguous = event(
        researcher,
        owner,
        "@Atlas and @Beacon both take this.",
        tags=[
            ["mention", researcher.link.agent_pubkey],
            ["mention", builder.link.agent_pubkey],
        ],
        offset=2,
    )
    unknown = event(
        researcher,
        owner,
        "@Unknown take this.",
        tags=[["mention", "f" * 64]],
        offset=3,
    )

    assert researcher._event_disposition(ordinary) == "accept"
    assert builder._event_disposition(ordinary) == "skip"
    assert researcher._event_disposition(addressed) == "skip"
    assert builder._event_disposition(addressed) == "accept"
    assert researcher._event_disposition(ambiguous) == "ambiguous"
    assert builder._event_disposition(ambiguous) == "skip"
    assert researcher._event_disposition(unknown) == "ambiguous"
    assert builder._event_disposition(unknown) == "skip"

    app = Conversations(researcher.service)
    message = ConversationMessage(
        ordinary["id"],
        researcher.link.link_id,
        researcher.link.principal_id,
        ordinary["content"],
        "buzz",
        ordinary["created_at"],
    )
    app.receive(researcher.link, message, event=ordinary)
    selected = app.process(researcher.link, message.message_id)
    with store.transaction() as tx:
        task = tx.task(selected.task_id)
    completed = researcher.service.run(task.task_id)

    reply = event(
        builder,
        owner,
        "@Beacon build the smallest useful version from that result.",
        tags=[
            ["mention", builder.link.agent_pubkey],
            ["e", ordinary["id"], "", "reply"],
        ],
        offset=4,
    )
    assert researcher._event_disposition(reply) == "skip"
    assert builder._event_disposition(reply) == "accept"
    delegated = ConversationMessage(
        reply["id"],
        builder.link.link_id,
        builder.link.principal_id,
        reply["content"],
        "buzz",
        reply["created_at"],
        reply_to=ordinary["id"],
    )
    app.receive(builder.link, delegated, event=reply)
    selected = app.process(builder.link, delegated.message_id)
    with store.transaction() as tx:
        child = tx.task(selected.task_id)
        assert len(tx.tasks()) == 2
    assert child.bot_id == "bot-beta"
    assert child.follows_task_id == task.task_id
    assert child.previous_result == completed.result
