"""Authenticated views and sends for one already-enrolled owner conversation."""

from dataclasses import asdict
from typing import Annotated

from fastapi import Depends, Query
from pydantic import Field

from radhouse.api.schemas import StrictModel, EnvelopeSchema, InputFileSchema
from radhouse.application.conversations import Conversations
from radhouse.channels.commands import Envelope
from radhouse.channels.nostr import encoded, sha256
from radhouse.domain.access import AuthContext
from radhouse.domain.conversations import ConversationMessage
from radhouse.domain.tasks import Rejected
from radhouse.domain.tasks import InputFile


class ConversationSend(StrictModel):
    envelope: EnvelopeSchema
    content: Annotated[str, Field(min_length=1, max_length=4096)]
    reply_to: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    files: Annotated[list[InputFileSchema], Field(max_length=4)] = Field(
        default_factory=list
    )


def install_conversation_routes(app, service, authenticate):
    conversations = Conversations(service)
    Actor = Annotated[AuthContext, Depends(authenticate)]
    Conversation = Annotated[str, Query(min_length=1, max_length=200)]
    Revision = Annotated[int, Query(ge=1)]

    @app.get("/conversations")
    def links(actor: Actor, conversation_id: Conversation, binding_revision: Revision):
        envelope = Envelope(
            actor.channel, "read", conversation_id, binding_revision, "read"
        )
        with service.store.transaction() as tx:
            binding = tx.binding(actor.channel, actor.subject, conversation_id)
            if binding is None:
                raise Rejected("binding_denied", 403)
            service._binding(tx, actor, envelope, binding.project_id)
            result = []
            for link in tx.conversation_links(actor.principal_id):
                if link.project_id != binding.project_id:
                    continue
                try:
                    conversations.authorize(tx, link)
                except Rejected as error:
                    if error.status == 403:
                        continue
                    raise
                bot = next(
                    (b for b in tx.bots(actor.principal_id) if b.bot_id == link.bot_id),
                    None,
                )
                result.append(
                    {
                        "link_id": link.link_id,
                        "bot_id": link.bot_id,
                        "display_name": bot.display_name if bot else link.bot_id,
                        "channel_id": link.channel_id,
                        "error_code": tx.conversation_status(link.link_id)[
                            "error_code"
                        ],
                    }
                )
            return result

    @app.get("/conversations/{link_id}/messages")
    def history(
        link_id: str,
        actor: Actor,
        conversation_id: Conversation,
        binding_revision: Revision,
        after: Annotated[int, Query(ge=0)] = 0,
        before: Annotated[int | None, Query(ge=1)] = None,
        tail: bool = False,
    ):
        envelope = Envelope(
            actor.channel, "read", conversation_id, binding_revision, "read"
        )
        return conversations.history(
            actor, envelope, link_id, after=after, before=before, tail=tail
        )

    @app.post("/conversations/{link_id}/messages")
    def send(link_id: str, body: ConversationSend, actor: Actor):
        with service.store.transaction() as tx:
            link = tx.conversation_link(link_id)
            if link is None or link.principal_id != actor.principal_id:
                raise Rejected("conversation_link_denied", 403)
            service._binding(tx, actor, body.envelope.command(), link.project_id)
            conversations.authorize(tx, link, write=True)
        identity = sha256(
            encoded([actor.channel, actor.subject, body.envelope.command_key])
        )
        message = ConversationMessage(
            identity,
            link.link_id,
            actor.principal_id,
            body.content,
            "radhouse",
            int(service._now().timestamp()),
            reply_to=body.reply_to,
            files=tuple(InputFile(**file.model_dump()) for file in body.files),
        )
        conversations.receive(link, message)
        return asdict(conversations.process(link, message.message_id))
