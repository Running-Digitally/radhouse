"""Native owner enrollment; a body cannot select a new agent authority."""

from typing import Annotated

from fastapi import Depends, Query
from pydantic import Field

from radhouse.api.schemas import EnvelopeSchema, StrictModel
from radhouse.channels.commands import Envelope
from radhouse.domain.access import AuthContext


class EnrollmentRequest(StrictModel):
    envelope: EnvelopeSchema
    link_id: Annotated[str, Field(min_length=1, max_length=200)]
    channel_id: Annotated[str, Field(min_length=1, max_length=36)]
    attestation: Annotated[list[str], Field(min_length=4, max_length=4)]


def install_enrollment_routes(app, enrollment, authenticate):
    Actor = Annotated[AuthContext, Depends(authenticate)]

    @app.get("/agent-enrollment")
    def candidates(
        actor: Actor,
        conversation_id: Annotated[str, Query(min_length=1, max_length=200)],
        binding_revision: Annotated[int, Query(ge=1)],
    ):
        envelope = Envelope(
            actor.channel, "read", conversation_id, binding_revision, "read"
        )
        return enrollment.list(actor, envelope)

    @app.post("/agent-enrollment")
    def enroll(actor: Actor, body: EnrollmentRequest):
        return enrollment.enroll(
            actor,
            body.envelope.command(),
            body.link_id,
            body.channel_id,
            body.attestation,
        )
