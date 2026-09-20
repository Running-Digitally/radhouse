"""One explicitly linked owner/agent conversation, independent of a chat client."""

from dataclasses import dataclass

from radhouse.domain.tasks import InputFile

BUZZ_THREAD_ANCESTRY_REJECTED = "buzz_thread_ancestry_rejected"


@dataclass(frozen=True)
class ConversationLink:
    link_id: str
    channel_id: str
    conversation_id: str
    principal_id: str
    owner_pubkey: str
    agent_pubkey: str
    bot_id: str
    project_id: str
    activated_at: int
    binding_revision: int = 1
    active: bool = True
    # A project group DM has one link per agent. Every link freezes the same
    # exact agent membership, while one link receives unaddressed messages.
    # Empty membership preserves old two-person DM snapshots.
    member_pubkeys: tuple[str, ...] = ()
    default_agent: bool = True


@dataclass(frozen=True)
class ConversationMessage:
    message_id: str
    link_id: str
    author: str
    content: str
    source: str
    created_at: int
    task_id: str | None = None
    reply_to: str | None = None
    state: str = "received"
    files: tuple[InputFile, ...] = ()
    task_state_revision: int | None = None
    # True only when ingress selected this agent from an explicit owner address.
    # Old retained snapshots omit the field and remain unaddressed.
    addressed: bool = False


@dataclass(frozen=True)
class MessageRoute:
    action: str
    task_id: str | None = None
    expected_revision: int | None = None
    follows_task_id: str | None = None
