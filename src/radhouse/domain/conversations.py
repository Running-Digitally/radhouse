"""One explicitly linked owner/agent conversation, independent of a chat client."""

from dataclasses import dataclass
from hashlib import sha256
from typing import Literal

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
    # A coordinator link owns project-channel ingress but never executes work.
    # It delegates each accepted owner message to one specialist link.
    coordinator: bool = False
    channel_kind: Literal["dm", "stream"] = "dm"

    @property
    def hermes_session_id(self) -> str:
        """Default Hermes session scoped to this owner, conversation and bot profile."""
        return self.hermes_session_id_for()

    def hermes_session_id_for(self, context_id: str | None = None) -> str:
        """Return the Hermes thread for this link and an optional fresh-context boundary."""
        identity_parts = [
            "radhouse-hermes-session-v1",
            self.link_id,
            self.principal_id,
            self.project_id,
            self.bot_id,
        ]
        if context_id:
            identity_parts.extend(("fresh-context", context_id))
        identity = "\0".join(identity_parts)
        return "rh-" + sha256(identity.encode("utf-8")).hexdigest()


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
    # Fresh-context boundaries and task bindings are frozen with the received
    # message so retries and delayed processing cannot pick a newer thread.
    context_id: str | None = None
    hermes_session_id: str | None = None
